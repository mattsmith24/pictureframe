import time
import datetime
import json
import requests
from collections import defaultdict
from urllib.parse import urlparse
from urllib.parse import parse_qs
from bs4 import BeautifulSoup

Default_grid_threshold = 1000

def is_new_ts(ts_datetime, last_dailydata_timestamp):
    yesterday = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    return (last_dailydata_timestamp == None or ts_datetime > last_dailydata_timestamp) and (ts_datetime.day == yesterday.day or ts_datetime < yesterday)

class SolarWeb:
    def __init__(self) -> None:
        self.config = None
        self.requests_session = None
        self.pv_system_id = None

    def get_image_select(self, pvdata_record):
        if not ("IsOnline" in pvdata_record) or not pvdata_record["IsOnline"] or not ("P_Grid" in pvdata_record):
            return "offline"
        grid_threshold = Default_grid_threshold
        if self.config != None and "grid_threshold" in self.config:
            grid_threshold = self.config["grid_threshold"]
        if pvdata_record["P_Grid"] > grid_threshold:
            return "grid"
        else:
            return "solar"


    def process_pvdata(self, pvdata_record):
        pvdata_record["img_select"] = self.get_image_select(pvdata_record)


    def login(self):
        print("Logging into solarweb")
        if self.requests_session != None:
            self.requests_session.close()
        self.requests_session = requests.Session()
        # Get a session
        external_login = self.requests_session.get("https://www.solarweb.com/Account/ExternalLogin")
        parsed_url = urlparse(external_login.url)
        query_dict = parse_qs(parsed_url.query)
        if external_login.status_code != 200 or not ("sessionDataKey" in query_dict):
            print("Error: Couldn't parse sessionDataKey from URL")
            print(external_login)
            print(external_login.url)
            print(external_login.text)
            return False
        session_data_key = query_dict['sessionDataKey'][0]
        # Login to fronius
        commonauth = self.requests_session.post("https://login.fronius.com/commonauth", data={
            "sessionDataKey": session_data_key,
            "username": self.config["username"],
            "password": self.config["password"],
            "chkRemember": "on"
        })
        if commonauth.status_code != 200:
            print("Error: posting to commonauth")
            print(commonauth)
            print(commonauth.url)
            print(commonauth.text)
            return False

        # Register login with Solarweb
        soup = BeautifulSoup(commonauth.text, 'html.parser')
        commonauth_form_data = {
            "code": soup.find("input", attrs={"name": "code"}).attrs["value"],
            "id_token": soup.find("input", attrs={"name": "id_token"}).attrs["value"],
            "state": soup.find("input", attrs={"name": "state"}).attrs["value"],
            "AuthenticatedIdPs": soup.find("input", attrs={"name": "AuthenticatedIdPs"}).attrs["value"],
            "session_state": soup.find("input", attrs={"name": "session_state"}).attrs["value"],
        }
        external_login_callback = self.requests_session.post("https://www.solarweb.com/Account/ExternalLoginCallback", data=commonauth_form_data)
        # Get PV system ID
        parsed_url = urlparse(external_login_callback.url)
        query_dict = parse_qs(parsed_url.query)
        if external_login_callback.status_code != 200 or not ('pvSystemId' in query_dict):
            print("Error: Couldn't parse pvSystemId from URL")
            print(external_login_callback)
            print(external_login_callback.url)
            print(external_login_callback.text)
            return False
        self.pv_system_id = query_dict['pvSystemId'][0]
        print("Logged into solarweb. Begin polling data")
        return True


    def load_config(self):
        with open("solarweb.json") as fd:
            self.config = json.load(fd)


    def run(self, terminate_event, pvdata_queue):
        done = False
        self.load_config()

        last_login_attempt = None
        while not done and not terminate_event.is_set():
            # Delay logging in if we just made an attempt
            if last_login_attempt != None and (datetime.datetime.now() - last_login_attempt).seconds < 30:
                time.sleep(1)
                continue

            last_login_attempt = datetime.datetime.now()
            if not self.login():
                continue

            # Check if it's time to bail
            if terminate_event.is_set():
                done = True
                break

            while True:
                # Get realtime solar data
                actual_data = self.requests_session.get(f"https://www.solarweb.com/ActualData/GetCompareDataForPvSystem?pvSystemId={self.pv_system_id}")
                if actual_data.status_code != 200:
                    print(actual_data)
                    print(actual_data.url)
                    print(actual_data.text)
                    break
                try:
                    pvdata_record = actual_data.json()
                except requests.exceptions.JSONDecodeError:
                    print("Exception while parsing pvdata")
                    print(actual_data.url)
                    print(actual_data.text)
                    break

                pvdata_record["datetime"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                self.process_pvdata(pvdata_record)
                pvdata_queue.put(pvdata_record)

                # Check if it's time to bail
                if terminate_event.is_set():
                    done = True
                    break
                # Delay and/or exit
                if terminate_event.wait(timeout=30.0):
                    done = True
                    break
        if self.requests_session != None:
            self.requests_session.close()


def main(terminate_event, pvdata_queue):
    solar_web = SolarWeb()
    solar_web.run(terminate_event, pvdata_queue)

