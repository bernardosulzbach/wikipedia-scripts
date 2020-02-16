import json
import webbrowser
import logging
from html.parser import HTMLParser
import urllib.parse

from selenium import webdriver

LOG_FILENAME = 'open-watchlist-pages.log'
LOGGING_FORMAT = '%(name)s - %(levelname)s - %(message)s'

WIKIPEDIA_BASE_URL = 'https://en.wikipedia.org'
WATCHLIST_URL = WIKIPEDIA_BASE_URL + '/wiki/Special:Watchlist'

SECRETS_FILE_PATH = './secrets.json'

USERNAME_JSON_FIELD = 'username'
PASSWORD_JSON_FIELD = 'password'

USERNAME_FIELD_XPATH = '//*[@id="wpName1"]'
PASSWORD_FIELD_XPATH = '//*[@id="wpPassword1"]'
LOGIN_BUTTON_XPATH = '//*[@id="wpLoginAttempt"]'

MAXIMUM_OPENED_PAGES = 25


def get_expected_field_from_json(json_object, field_name):
    assert json_object is not None
    if field_name not in json_object:
        raise Exception('Expected {} in the JSON object.'.format(USERNAME_JSON_FIELD))
    return json_object[field_name]


def read_credentials():
    with open(SECRETS_FILE_PATH) as secrets_file:
        json_object = json.loads(secrets_file.read())
        username = get_expected_field_from_json(json_object, USERNAME_JSON_FIELD)
        password = get_expected_field_from_json(json_object, PASSWORD_JSON_FIELD)
        return username, password


def fill_input_field(driver, xpath, keys):
    input_field = driver.find_element_by_xpath(xpath)
    input_field.send_keys(keys)


def get_attribute(attributes, required_attribute_name: str):
    for attribute_name, attribute_value in attributes:
        if attribute_name == required_attribute_name:
            return attribute_value
    return None


def has_class(attributes, class_name) -> bool:
    for attribute_name, attribute_value in attributes:
        if attribute_name == 'class':
            return class_name in attribute_value.split(' ')
    return False


class WatchlistEntry:
    def __init__(self, page_title: str):
        assert isinstance(page_title, str)
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
        self.ignoring_everything = False
        self.printing_data = False
        self.watchlist_entries: [WatchlistEntry] = []
        self.collecting_diff = False
        self.next_seen = None

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


def set_query_parameter(query: str, parameter_name: str, new_parameter_value: str) -> str:
    assert isinstance(query, str)
    assert isinstance(parameter_name, str)
    assert isinstance(new_parameter_value, str)
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


def main():
    logging.basicConfig(level=logging.INFO, filename=LOG_FILENAME, filemode='a', format=LOGGING_FORMAT)
    options = webdriver.FirefoxOptions()
    driver = webdriver.Firefox(executable_path='./dependencies/geckodriver', options=options)

    driver.get(WATCHLIST_URL)

    username, password = read_credentials()
    fill_input_field(driver, USERNAME_FIELD_XPATH, username)
    fill_input_field(driver, PASSWORD_FIELD_XPATH, password)
    driver.find_element_by_xpath(LOGIN_BUTTON_XPATH).click()
    opened_pages = 0
    for watchlist_section in driver.find_elements_by_xpath('//*[@id="mw-content-text"]/div[4]/ul'):
        watchlist_html = watchlist_section.get_attribute('innerHTML')
        parser = WatchlistParser()
        parser.feed(watchlist_html)
        for i, entry in enumerate(parser.watchlist_entries):
            if entry.seen:
                logging.info('Skipped {} as it was seen.'.format(entry.page_title))
            elif opened_pages < MAXIMUM_OPENED_PAGES:
                url = set_query_parameter(WIKIPEDIA_BASE_URL + entry.page_url, 'diff', '0')
                webbrowser.open(url)
                opened_pages += 1
                logging.info('Opened {} ({}).'.format(entry.page_title, url))
    driver.quit()


if __name__ == '__main__':
    main()
