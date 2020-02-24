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

SCRIPT_NAME = 'open-watchlist-pages'

DATABASE_FILENAME = SCRIPT_NAME + '.db'

LOG_FILENAME = SCRIPT_NAME + '.log'
LOG_FORMAT = '[%(asctime)s] %(levelname)s %(module)s.%(funcName)s: %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%dT%H:%M:%S%z'

COUNT_ARGUMENT_NAME = 'count'

WIKIPEDIA_BASE_URL = 'https://en.wikipedia.org'
WATCHLIST_URL = WIKIPEDIA_BASE_URL + '/wiki/Special:Watchlist'

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


def get_attribute(attributes: List[Tuple[str, str]], required_attribute_name: str) -> Optional[str]:
    for attribute_name, attribute_value in attributes:
        if attribute_name == required_attribute_name:
            return attribute_value
    return None


def has_class(attributes: List[Tuple[str, str]], class_name: str) -> bool:
    for attribute_name, attribute_value in attributes:
        if attribute_name == 'class':
            return class_name in attribute_value.split(' ')
    return False


class WatchlistEntry:
    def __init__(self, page_title: str):
        self.page_title = page_title
        self.page_url = None
        self.user = None
        self.user_url = None
        self.diff = None
        self.seen = None

    def __str__(self):
        return '{} by {} ({})'.format(self.page_title, self.user, self.diff)


class WatchlistParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ignoring_everything: bool = False
        self.printing_data: bool = False
        self.watchlist_entries: [WatchlistEntry] = []
        self.collecting_diff: bool = False
        self.next_seen: Optional[bool] = None

    def handle_starttag(self, tag, attributes):
        if self.ignoring_everything:
            return
        if has_class(attributes, 'mw-changeslist-line'):
            if has_class(attributes, 'mw-changeslist-line-watched'):
                self.next_seen = False
            elif has_class(attributes, 'mw-changeslist-line-not-watched'):
                self.next_seen = True
            else:
                raise Exception('Should not have a line that does not define if it has been seen or not.')
        if has_class(attributes, 'mw-changeslist-diff'):
            self.watchlist_entries.append(WatchlistEntry(get_attribute(attributes, 'title')))
            self.watchlist_entries[-1].page_url = get_attribute(attributes, 'href')
            if self.next_seen is None:
                raise Exception('Should not have unknown "seen" about an entry.')
            self.watchlist_entries[-1].seen = self.next_seen
            self.next_seen = None
        if has_class(attributes, 'mw-userlink'):
            self.watchlist_entries[-1].user = get_attribute(attributes, 'title')
            self.watchlist_entries[-1].user_link = get_attribute(attributes, 'href')
        if has_class(attributes, 'mw-diff-bytes'):
            self.collecting_diff = True

    def handle_endtag(self, tag):
        if self.ignoring_everything:
            return

    def handle_data(self, data):
        if self.ignoring_everything:
            return
        if self.collecting_diff:
            self.watchlist_entries[-1].diff = data
            self.collecting_diff = False

    def error(self, message):
        raise Exception(message)


def set_query_parameter(query: str, parameter_name: str, new_parameter_value: str) -> str:
    parsed_url = urllib.parse.urlparse(query)
    query_parameters = urllib.parse.parse_qs(parsed_url.query, strict_parsing=True)
    query_parameters.update({parameter_name: [new_parameter_value]})
    scheme = parsed_url.scheme
    netloc = parsed_url.netloc
    path = parsed_url.path
    params = parsed_url.params
    query = urllib.parse.urlencode(query_parameters, doseq=True, quote_via=urllib.parse.quote)
    fragment = parsed_url.fragment
    url_bits = (scheme, netloc, path, params, query, fragment)
    return urllib.parse.urlunparse(url_bits)


def get_iso_date():
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

    def ensure_tables_exist(self):
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
        cursor.execute("""CREATE INDEX IF NOT EXISTS page_name_index ON page (name)""")
        cursor.execute("""CREATE INDEX IF NOT EXISTS page_open_name_date_index ON page_open (name, date)""")

    def add_page_open(self, page_title: str):
        if self.connection is None:
            logging.warning('Tried to add a page open but is not connected to the Database.')
            return
        cursor = self.connection.cursor()
        cursor.execute("INSERT OR IGNORE INTO page VALUES (?)", (page_title,))
        cursor.execute("INSERT INTO page_open VALUES (?, ?)", (page_title, get_iso_date()))


def open_pages(driver, maximum_opened_pages):
    driver.get(WATCHLIST_URL)

    username, password = read_credentials()
    fill_input_field(driver, USERNAME_FIELD_XPATH, username)
    fill_input_field(driver, PASSWORD_FIELD_XPATH, password)
    driver.find_element_by_xpath(LOGIN_BUTTON_XPATH).click()

    fetched_pages = 0
    opened_pages = 0
    unseen_but_not_opened_pages = 0

    wait = WebDriverWait(driver, 10)
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
                    url = set_query_parameter(WIKIPEDIA_BASE_URL + entry.page_url, 'diff', '0')
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
        open_pages(driver, maximum_opened_pages)
    except Exception as e:
        logging.exception(e)
    finally:
        driver.quit()


if __name__ == '__main__':
    main()
