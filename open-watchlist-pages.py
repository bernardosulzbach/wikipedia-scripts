import argparse
import datetime
import json
import logging
import sqlite3
import time
import urllib.parse
import webbrowser
from html.parser import HTMLParser
from typing import Tuple, List, Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait

WATCHLIST_XPATH = '//*[@id="mw-content-text"]/div[4]/ul'
EDIT_WATCHLIST_XPATH = '//div/div/span/label/a[1]'

PAGE_HISTORY_SEEN_LINE_XPATH = 'li[not(contains(@class, "mw-history-line-updated"))]'
PAGE_HISTORY_DIFFERENCE_URL_XPATH = '//*[@id="pagehistory"]/{}/span[1]/span[1]/a'.format(PAGE_HISTORY_SEEN_LINE_XPATH)

SCRIPT_NAME = 'open-watchlist-pages'

# In seconds
WEBDRIVER_TIMEOUT = 10

DATABASE_FILENAME = SCRIPT_NAME + '.db'

LOG_FILENAME = SCRIPT_NAME + '.log'
LOG_FORMAT = '[%(asctime)s] %(levelname)s %(module)s.%(funcName)s: %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%dT%H:%M:%S%z'

COUNT_ARGUMENT_NAME = 'count'

WIKIPEDIA_BASE_URL = 'https://en.wikipedia.org'
WATCHLIST_URL = WIKIPEDIA_BASE_URL + '/wiki/Special:Watchlist'
EDIT_WATCHLIST_URL = WIKIPEDIA_BASE_URL + '/wiki/Special:EditWatchlist'
LOGIN_URL = WIKIPEDIA_BASE_URL + '/wiki/Special:UserLogin'

SECRETS_FILE_PATH = './secrets.json'

USERNAME_JSON_FIELD = 'username'
PASSWORD_JSON_FIELD = 'password'

USERNAME_FIELD_XPATH = '//*[@id="wpName1"]'
PASSWORD_FIELD_XPATH = '//*[@id="wpPassword1"]'
LOGIN_BUTTON_XPATH = '//*[@id="wpLoginAttempt"]'


def get_expected_field_from_json(json_object, field_name):
    assert json_object is not None
    if field_name not in json_object:
        raise Exception('Expected {} in the JSON object.'.format(USERNAME_JSON_FIELD))
    return json_object[field_name]


def read_credentials() -> Tuple[str, str]:
    with open(SECRETS_FILE_PATH) as secrets_file:
        json_object = json.loads(secrets_file.read())
        username = get_expected_field_from_json(json_object, USERNAME_JSON_FIELD)
        password = get_expected_field_from_json(json_object, PASSWORD_JSON_FIELD)
        return username, password


def fill_input_field(driver, xpath, keys):
    input_field = driver.find_element_by_xpath(xpath)
    input_field.send_keys(keys)


def get_attribute(attributes: List[Tuple[str, str]], name: str) -> Optional[str]:
    for attribute_name, attribute_value in attributes:
        if attribute_name == name:
            return attribute_value
    return None


def has_attribute(attributes: List[Tuple[str, str]], name: str) -> bool:
    return get_attribute(attributes, name) is not None


def has_class(attributes: List[Tuple[str, str]], name: str) -> bool:
    class_attribute = get_attribute(attributes, 'class')
    if class_attribute:
        return name in class_attribute.split(' ')
    return False


class WatchlistEntry:
    def __init__(self, page_title: str):
        self.page_title: str = page_title
        self.history_url: Optional[str] = None
        self.user: Optional[str] = None
        self.user_url: Optional[str] = None
        self.diff: Optional[str] = None
        self.seen: Optional[bool] = None

    def __str__(self):
        return '{} by {} ({})'.format(self.page_title, self.user, self.diff)


class WatchlistParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.printing_data: bool = False
        self.watchlist_entries: [WatchlistEntry] = []
        self.collecting_diff: bool = False
        self.next_seen: Optional[bool] = None
        self.skipping_log_action: bool = False

    def handle_starttag(self, tag, attributes):
        if has_class(attributes, 'mw-changeslist-line'):
            if has_attribute(attributes, 'data-mw-logaction'):
                log_action_name = get_attribute(attributes, 'data-mw-logaction')
                logging.warning('Ignoring a log action of type {}.'.format(log_action_name))
                self.skipping_log_action = True
            elif has_class(attributes, 'mw-changeslist-line-watched'):
                self.next_seen = False
                self.skipping_log_action = False
            elif has_class(attributes, 'mw-changeslist-line-not-watched'):
                self.next_seen = True
                self.skipping_log_action = False
            else:
                raise Exception('Should not have a line that does not define if it has been seen or not.')
        if self.skipping_log_action:
            return
        if has_class(attributes, 'mw-changeslist-history'):
            self.watchlist_entries.append(WatchlistEntry(get_attribute(attributes, 'title')))
            self.watchlist_entries[-1].history_url = WIKIPEDIA_BASE_URL + get_attribute(attributes, 'href')
            if self.next_seen is None:
                raise Exception('Should not have unknown "seen" about an entry.')
            self.watchlist_entries[-1].seen = self.next_seen
            self.next_seen = None
        if has_class(attributes, 'mw-userlink'):
            self.watchlist_entries[-1].user = get_attribute(attributes, 'title')
            self.watchlist_entries[-1].user_link = get_attribute(attributes, 'href')
        if has_class(attributes, 'mw-diff-bytes'):
            self.collecting_diff = True

    def handle_data(self, data):
        if self.collecting_diff:
            self.watchlist_entries[-1].diff = data
            self.collecting_diff = False

    def error(self, message):
        raise Exception(message)


def get_query_parameters(query: str) -> dict:
    parsed_url = urllib.parse.urlparse(query)
    return urllib.parse.parse_qs(parsed_url.query, strict_parsing=True)


def set_query_parameters(query: str, query_parameters: dict) -> str:
    parsed_url = urllib.parse.urlparse(query)
    scheme = parsed_url.scheme
    netloc = parsed_url.netloc
    path = parsed_url.path
    params = parsed_url.params
    query = urllib.parse.urlencode(query_parameters, doseq=True, quote_via=urllib.parse.quote)
    fragment = parsed_url.fragment
    return urllib.parse.urlunparse((scheme, netloc, path, params, query, fragment))


def remove_query_parameter(query: str, parameter_name: str) -> str:
    query_parameters = get_query_parameters(query)
    query_parameters.pop(parameter_name)
    return set_query_parameters(query, query_parameters)


def set_query_parameter(query: str, parameter_name: str, new_parameter_value: str) -> str:
    query_parameters = get_query_parameters(query)
    query_parameters.update({parameter_name: [new_parameter_value]})
    return set_query_parameters(query, query_parameters)


def get_iso_date() -> str:
    # Calculate the offset taking into account daylight saving time
    utc_offset_sec = time.altzone if time.localtime().tm_isdst else time.timezone
    utc_offset = datetime.timedelta(seconds=-utc_offset_sec)
    return datetime.datetime.now().replace(tzinfo=datetime.timezone(offset=utc_offset)).isoformat()


class Database:
    def __init__(self, filename: str):
        self.connection: Optional[sqlite3.Connection] = None
        self.filename: str = filename

    def __enter__(self):
        self.connection = sqlite3.connect(self.filename)
        self.ensure_tables_exist()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.connection.commit()
        self.connection.close()

    def ensure_tables_exist(self) -> None:
        if self.connection is None:
            logging.warning('Tried to ensure tables exist but is not connected to the database.')
            return
        cursor = self.connection.cursor()
        cursor.execute("""SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'page'""")
        if cursor.fetchone() is None:
            # Create the tables if they don't exist.
            cursor.execute("""CREATE TABLE page
(
    name TEXT PRIMARY KEY
)""")
            cursor.execute("""CREATE TABLE page_open
(
    name TEXT,
    date TEXT,
    PRIMARY KEY (name, date),
    FOREIGN KEY (name) REFERENCES pages (name)
)""")
            cursor.execute("""CREATE TABLE watchlist_page
(
    name TEXT,
    date TEXT,
    PRIMARY KEY (name),
    FOREIGN KEY (name) REFERENCES page (name)
)""")
        cursor.execute("""CREATE INDEX IF NOT EXISTS page_name_index ON page (name)""")
        cursor.execute("""CREATE INDEX IF NOT EXISTS page_open_name_date_index ON page_open (name, date)""")

    def add_page_open(self, page_title: str):
        if self.connection is None:
            logging.warning('Tried to add a page open but is not connected to the database.')
            return
        cursor = self.connection.cursor()
        cursor.execute("INSERT OR IGNORE INTO page VALUES (?)", (page_title,))
        cursor.execute("INSERT INTO page_open VALUES (?, ?)", (page_title, get_iso_date()))

    def add_watchlist_page(self, page_title: str):
        if self.connection is None:
            logging.warning('Tried to add a watchlist page but is not connected to the database.')
            return
        cursor = self.connection.cursor()
        now = get_iso_date()
        cursor.execute("INSERT OR IGNORE INTO page VALUES (?)", (page_title,))
        cursor.execute("""INSERT INTO watchlist_page
VALUES (?, ?) ON CONFLICT (name) DO UPDATE SET date=?""", (page_title, now, now))


def login(driver: webdriver.Firefox) -> None:
    driver.get(LOGIN_URL)

    username, password = read_credentials()
    fill_input_field(driver, USERNAME_FIELD_XPATH, username)
    fill_input_field(driver, PASSWORD_FIELD_XPATH, password)
    driver.find_element_by_xpath(LOGIN_BUTTON_XPATH).click()


def update_watchlist(driver: webdriver.Firefox) -> None:
    driver.get(EDIT_WATCHLIST_URL)

    wait = WebDriverWait(driver, WEBDRIVER_TIMEOUT)
    condition = expected_conditions.presence_of_all_elements_located((By.XPATH, EDIT_WATCHLIST_XPATH))
    with Database(DATABASE_FILENAME) as database:
        for watchlist_item in wait.until(condition):
            item_text = watchlist_item.get_attribute('innerHTML')
            database.add_watchlist_page(item_text)


def open_pages(driver: webdriver.Firefox, maximum_opened_pages: int) -> None:
    driver.get(WATCHLIST_URL)

    fetched_pages = 0
    opened_pages = 0
    unseen_but_not_opened_pages = 0

    wait = WebDriverWait(driver, WEBDRIVER_TIMEOUT)
    condition = expected_conditions.presence_of_all_elements_located((By.XPATH, WATCHLIST_XPATH))

    with Database(DATABASE_FILENAME) as database:
        for watchlist_section in wait.until(condition):
            watchlist_html = watchlist_section.get_attribute('innerHTML')
            parser = WatchlistParser()
            parser.feed(watchlist_html)
            for i, entry in enumerate(parser.watchlist_entries):
                if entry.seen:
                    logging.info('Skipped {} as it was seen.'.format(entry.page_title))
                elif opened_pages < maximum_opened_pages:
                    # Get the URL of the proper difference.
                    driver.get(entry.history_url)
                    xpath = PAGE_HISTORY_DIFFERENCE_URL_XPATH
                    first_seen_revision = expected_conditions.presence_of_element_located((By.XPATH, xpath))
                    url = wait.until(first_seen_revision).get_attribute('href')
                    driver.back()
                    # Open this difference for human inspection.
                    webbrowser.open(url, autoraise=False)
                    database.add_page_open(entry.page_title)
                    opened_pages += 1
                    logging.info('Opened {} ({}).'.format(entry.page_title, url))
                else:
                    unseen_but_not_opened_pages += 1
            fetched_pages += len(parser.watchlist_entries)
        logging.info('Fetched {} page(s).'.format(fetched_pages))
        logging.info('Unseen entries that were not opened: {}.'.format(unseen_but_not_opened_pages))


def main():
    parser = argparse.ArgumentParser(description='Open the most recent unseen pages from your Wikipedia watchlist.')
    parser.add_argument(COUNT_ARGUMENT_NAME, type=int, help='the number of pages to open')
    arguments = vars(parser.parse_args())
    maximum_opened_pages = arguments[COUNT_ARGUMENT_NAME]

    logging.basicConfig(level=logging.INFO, filename=LOG_FILENAME, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    options = webdriver.FirefoxOptions()
    options.add_argument('-headless')
    driver = webdriver.Firefox(executable_path='./dependencies/geckodriver', options=options)
    try:
        login(driver)
        update_watchlist(driver)
        open_pages(driver, maximum_opened_pages)
    except Exception as e:
        logging.exception(e)
    finally:
        driver.quit()


if __name__ == '__main__':
    main()
