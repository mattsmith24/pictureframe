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
    def __init__(self, terminate_event, pvdata_queue) -> None:
        self.terminate_event = terminate_event
        self.pvdata_queue = pvdata_queue
        self.config = None
        self.last_dailydata_timestamp = None
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


    def init_dailydata(self):
        yesterday = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
        try:
            with open(f"dailydata-{yesterday.year}.csv", "r") as fd:
                dailydata = fd.readlines()
                self.last_dailydata_timestamp = datetime.datetime.fromisoformat(dailydata[-1].split(",")[0])
        except FileNotFoundError:
            pass
        except IndexError:
            pass


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


    def get_chart(self, chartday, interval, view):
        chart_data = self.requests_session.get(f"https://www.solarweb.com/Chart/GetChartNew?pvSystemId={self.pv_system_id}&year={chartday.year}&month={chartday.month}&day={chartday.day}&interval={interval}&view={view}")
        if chart_data.status_code != 200:
            print(chart_data)
            print(chart_data.url)
            print(chart_data.text)
            return None
        return chart_data.json()


    def process_chart_data(self):
        yesterday = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)

        # Get cumulative solar production data for yesterday, this is so that we get
        # full days totals across the month boundary
        # Chart data is a json structure that wraps an array of timestamp / kwh values.
        # The timestamps can be parsed with datetime.datetime.fromtimestamp(val / 1000, tz=datetime.timezone.utc)
        chart_month_production = self.get_chart(yesterday, "month", "production")
        if chart_month_production == None:
            return False

        found_new_data = False
        for data_tuple in chart_month_production["settings"]["series"][0]["data"]:
            ts_datetime = datetime.datetime.fromtimestamp(int(data_tuple[0])/1000, tz=datetime.timezone.utc)
            if is_new_ts(ts_datetime, self.last_dailydata_timestamp):
                found_new_data = True
                break
        if not found_new_data:
            return True

        # Get cumulative solar consumption data for the current month
        chart_month_consumption = self.get_chart(yesterday, "month", "consumption")
        if chart_month_consumption == None:
            return False

        # Extract the data series from the charts
        daily_data_tuples = {}
        for series in chart_month_production["settings"]["series"]:
            if series["name"] == "Energy to grid":
                daily_data_tuples["feedin"] = series["data"]
            if series["name"] == "Consumed directly":
                daily_data_tuples["direct"] = series["data"]
        for series in chart_month_consumption["settings"]["series"]:
            if series["name"] == "Energy from grid":
                daily_data_tuples["grid"] = series["data"]
        # Rearrange the series to group all series by timestamp
        daily_data_dict = {}
        for label in ["grid", "feedin", "direct"]:
            for tuple in daily_data_tuples[label]:
                ts = tuple[0]
                if ts not in daily_data_dict:
                    # Using defaultdict here will handle cases where these is a missing series for a timestamp
                    # and just return 0 in the next loop
                    daily_data_dict[ts] = defaultdict(int)
                daily_data_dict[ts][label] = tuple[1]
        with open(f"dailydata-{yesterday.year}.csv", "a") as fd:
            for ts,data_dict in daily_data_dict.items():
                ts_datetime = datetime.datetime.fromtimestamp(int(ts)/1000, tz=datetime.timezone.utc)
                if is_new_ts(ts_datetime, self.last_dailydata_timestamp):
                    # solar generation = feedin + direct consumption
                    # house user = direct consumption + grid
                    entry = [ts_datetime.isoformat(), data_dict["grid"], data_dict["direct"] + data_dict["feedin"], data_dict["direct"] + data_dict["grid"]]
                    entry_str = ",".join([str(e) for e in entry])
                    fd.write(entry_str + "\n")
            self.last_dailydata_timestamp = ts_datetime
        return True


    def run(self):
        done = False
        with open("solarweb.json") as fd:
            self.config = json.load(fd)
        self.init_dailydata()

        last_login_attempt = None
        today = datetime.datetime.now(datetime.timezone.utc)
        pvdatalog = open(f"pvdata-{today.year}-{today.month:02}-{today.day:02}.log", "a")
        while not done and not self.terminate_event.is_set():
            # Delay logging in if we just made an attempt
            if last_login_attempt != None and (datetime.datetime.now() - last_login_attempt).seconds < 30:
                time.sleep(1)
                continue

            last_login_attempt = datetime.datetime.now()
            if not self.login():
                continue

            # Check if it's time to bail
            if self.terminate_event.is_set():
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
                pvdata_record = actual_data.json()
                pvdata_record["datetime"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                logline = json.dumps(pvdata_record)
                print(logline, file=pvdatalog, flush=True)
                self.process_pvdata(pvdata_record)
                self.pvdata_queue.put(pvdata_record)

                # Check if it's time to bail
                if self.terminate_event.is_set():
                    done = True
                    break

                if not self.process_chart_data():
                    break

                # Delay and/or exit
                if self.terminate_event.wait(timeout=30.0):
                    done = True
                    break
        pvdatalog.close()
        if self.requests_session != None:
            self.requests_session.close()


def main(terminate_event, pvdata_queue):
    solar_web = SolarWeb(terminate_event, pvdata_queue)
    solar_web.run()
