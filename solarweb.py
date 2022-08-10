import time
import datetime
import json
import requests
from urllib.parse import urlparse
from urllib.parse import parse_qs
from bs4 import BeautifulSoup

Default_grid_threshold = 1000
config = None


def get_image_select(pvdata_record):
    global config
    if not pvdata_record["IsOnline"]:
        return "offline"
    grid_threshold = Default_grid_threshold
    if config != None and "grid_threshold" in config:
        grid_threshold = config["grid_threshold"]
    if pvdata_record["P_Grid"] > grid_threshold:
        return "grid"
    else:
        return "solar"


def process_pvdata(pvdata_record):
    pvdata_record["img_select"] = get_image_select(pvdata_record)


def main(terminate_event, pvdata_queue):
    global config
    done = False
    with open("solarweb.json") as fd:
        config = json.load(fd)

    last_login_attempt = None

    with open("pvdata.log", "a") as pvdatalog:
        while not done and not terminate_event.is_set():
            # Delay logging in if we just made an attempt
            if last_login_attempt != None and (datetime.datetime.now() - last_login_attempt).seconds < 30:
                time.sleep(1)
                continue
            print("Logging into solarweb")
            last_login_attempt = datetime.datetime.now()
            s = requests.Session()
            # Get a session
            external_login = s.get("https://www.solarweb.com/Account/ExternalLogin")
            parsed_url = urlparse(external_login.url)
            query_dict = parse_qs(parsed_url.query)
            if external_login.status_code != 200 or not ("sessionDataKey" in query_dict):
                print("Error: Couldn't parse sessionDataKey from URL")
                print(external_login)
                print(external_login.url)
                print(external_login.text)
                continue
            session_data_key = query_dict['sessionDataKey'][0]
            # Login to fronius
            commonauth = s.post("https://login.fronius.com/commonauth", data={
                "sessionDataKey": session_data_key,
                "username": config["username"],
                "password": config["password"],
                "chkRemember": "on"
            })
            if commonauth.status_code != 200:
                print("Error: posting to commonauth")
                print(commonauth)
                print(commonauth.url)
                print(commonauth.text)
                continue

            # Register login with Solarweb
            soup = BeautifulSoup(commonauth.text, 'html.parser')
            commonauth_form_data = {
                "code": soup.find("input", attrs={"name": "code"}).attrs["value"],
                "id_token": soup.find("input", attrs={"name": "id_token"}).attrs["value"],
                "state": soup.find("input", attrs={"name": "state"}).attrs["value"],
                "AuthenticatedIdPs": soup.find("input", attrs={"name": "AuthenticatedIdPs"}).attrs["value"],
                "session_state": soup.find("input", attrs={"name": "session_state"}).attrs["value"],
            }
            external_login_callback = s.post("https://www.solarweb.com/Account/ExternalLoginCallback", data=commonauth_form_data)
            # Get PV system ID
            parsed_url = urlparse(external_login_callback.url)
            query_dict = parse_qs(parsed_url.query)
            if external_login_callback.status_code != 200 or not ('pvSystemId' in query_dict):
                print("Error: Couldn't parse pvSystemId from URL")
                print(external_login_callback)
                print(external_login_callback.url)
                print(external_login_callback.text)
                continue
            pv_system_id = query_dict['pvSystemId'][0]
            print("Logged into solarweb. Begin polling data")
            while True:
                actual_data = s.get(f"https://www.solarweb.com/ActualData/GetCompareDataForPvSystem?pvSystemId={pv_system_id}")
                if actual_data.status_code != 200:
                    print(actual_data)
                    print(actual_data.url)
                    print(actual_data.text)
                    break
                pvdata_record = actual_data.json()
                pvdata_record["datetime"] = datetime.datetime.now().isoformat()
                logline = json.dumps(pvdata_record)
                pvdatalog.write(logline + "\n")
                process_pvdata(pvdata_record)
                pvdata_queue.put(pvdata_record)
                # Delay and/or exit
                if terminate_event.wait(timeout=30.0):
                    done = True
                    break