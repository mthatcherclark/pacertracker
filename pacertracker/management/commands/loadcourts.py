import sys
import re
import requests
import datetime

from bs4 import BeautifulSoup
from concurrent import futures
from timeit import default_timer as timer
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

from django.utils.timezone import utc
from django.core.management.base import BaseCommand, CommandError

from pacertracker.models import Court

def get_type(raw_name, ecf_url):
    if 'Supreme Court' in raw_name:
        type = 'S'
    elif 'Pacer Case' in raw_name:
        type = False
    elif '(web)' in raw_name:
        type = False
    elif '(asbestos)' in raw_name:
        type = False
    elif 'BAP' in raw_name:
        type = False  
    elif ('ecf.ca' in ecf_url
        and 'b.usc' not in ecf_url 
        and 'd.usc' not in ecf_url):
        #This conditional takes care of California courts,
        #which (like Appeals) have URLs containing ecf.ca
        type = 'A'
    elif 'ecf.jpml' in ecf_url:
        type = 'M'
    elif 'ecf.cofc' in ecf_url:
        type = 'F'
    elif 'ecf.cit' in ecf_url:
        type = 'I'
    elif 'd.usc' in ecf_url:
        type = 'D'
    elif 'b.usc' in ecf_url:
        type = 'B'
    else:
        type = False
    
    return type

def get_name(raw_name):
    name = raw_name.replace('U.S. Court of ', '').replace('Appeals, ', '')
    name = name.replace(' Bankruptcy Court', '').replace(' District Court', '')
    name = name.replace(' of the United States', '').replace(' Bankruptcy','').strip()
    
    return name
    
def requests_retry_session(
    retries=3,
    backoff_factor=0.1,
    session=None,
):
    # https://urllib3.readthedocs.io/en/latest/reference/urllib3.util.html
    # https://www.peterbe.com/plog/best-practice-with-retries-with-requests
    session = session or requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    
    return session
    
def check_feed(info_url, feed_url):
    if feed_url != '':
        # Try to download the feed and see if it has entries
        try:
            response = requests_retry_session().get(
                feed_url,
                verify=False,
                timeout=5
            )
            feed = BeautifulSoup(response.content, "lxml-xml")
        except requests.exceptions.ConnectionError as e:
            # Max Retries Exceeded
            feed = None

        if feed and (not feed.channel or not feed.title or '404' in feed.title.text):
            feed_check = False
            publishes_all = False
            filing_types = ''
        elif feed and feed.channel.description and 'not configured' in feed.channel.description.text:
            feed_check = False
            publishes_all = False
            filing_types = ''
        elif feed and feed.channel.description:
            feed_check = True
            filing_types = feed.channel.description.text
            
            if (len(filing_types) > 24 and 'all' in filing_types[24:].lower()
                and 'entries of type' in filing_types):
                publishes_all = True
                filing_types = 'All filings'
            elif (len(filing_types) > 24 and filing_types[24:] != '' 
                  and 'entries of type' not in filing_types):
                publishes_all = False
            elif len(filing_types) > 24 and filing_types[24:] != '':
                publishes_all = False
                filing_types = filing_types[24:]
            else:
                publishes_all = False
                filing_types = ''
        else:
            feed_check = False
            publishes_all = False
            filing_types = ''
    else:
        feed_check = False
        publishes_all = False
        filing_types = ''
    
    # Even if the feed was not properly formatted,
    # we still need to mark in PACER Tracker those courts that 
    # are listed as having a feed on the courts website
    try:
        response = requests.get(info_url, timeout=5)
    except requests.exceptions.ReadTimeout as e:
        response = None
    except requests.exceptions.ConnectionError as e:
        # Max retries exceeded
        response = None

    if 'servlet/TransportRoom' in info_url:
        # Appeals courts have a different info page.
        if response and 'RSS Feed' in response.text:
            info_check = True
        else:
            info_check = False
    elif response:
        soup = BeautifulSoup(response.text, 'lxml')
        info_check = soup.find('i', class_='fa-rss')
    else:
        info_check = False
        
    if not feed_check and info_check:
        feed_check = True
        publishes_all = False
        filing_types = ''

    return feed_check, publishes_all, filing_types
    
def update_court(tr_tag):
    raw_name = tr_tag.find('td', class_='views-field-court-name').a.string
    if 'Supreme Court' in raw_name:
        # Supreme Court has no base_ecf_url so we just give it a fake one...
        base_ecf_url = 'https://ecf.supremecourt.gov/'
    else:
        base_ecf_url = tr_tag.find('td', class_='views-field-court-app-type').a['href']
        if base_ecf_url[-1] != '/':
            base_ecf_url += '/'
    
    if get_type(raw_name, base_ecf_url):
        type = get_type(raw_name, base_ecf_url)
    else:
        print('Did not save %s.' % raw_name)
        return None
    
    # Appeals courts have a different info page.
    # While the Supreme Court has no normal info page, we will check
    # the normal info page to see if an RSS icon pops up anyway.
    if type == 'A':
        info_url_base = base_ecf_url
        info_url_ext = 'n/beam/servlet/TransportRoom?servlet=CourtInfo.jsp'
        info_url = info_url_base + info_url_ext
    else:
        info_url_base = 'https://pacer.uscourts.gov'
        info_url_ext = tr_tag.find('td', class_='views-field-court-name').a['href']
        info_url = info_url_base + info_url_ext
    
    name = get_name(raw_name)
    
    # Add the feed url even if it doesn't say it has a feed
    if (type == 'D' or type == 'B' or type == 'F' or type == 'I' or type == 'M'):
        feed_url = base_ecf_url + 'cgi-bin/rss_outside.pl'
    elif type == 'A':
        feed_url = base_ecf_url + 'cmecf/servlet/TransportRoom?servlet=RSSGenerator'
    else:
        feed_url = ''
    
    has_feed, publishes_all, filing_types = check_feed(info_url, feed_url)
    
    website = base_ecf_url.replace('https://ecf','http://www')
    
    court_check = Court.objects.filter(website=website)
    
    if court_check.exists() and court_check.count() == 1:
        if has_feed and not court_check[0].has_feed and 'nyed' not in feed_url:
            print('This court now has a feed: %s - %s' % (name, court_check[0].get_type_display()))
        elif not has_feed and court_check[0].has_feed:
            print('This court no longer has a feed: %s - %s' % (name, court_check[0].get_type_display()))
        
        if 'nyed' not in feed_url: # This ensures the NYED keeps its fancy one-off URL
            court_check.update(name=name, type=type, has_feed=has_feed, feed_url=feed_url, website=website,
                                publishes_all=publishes_all, filing_types=filing_types)
            
    else:
        #To ensure all entries from current RSS files are retrieved when first scraped for new courts,
        #we set the last_updated to one year ago (roughly).
        last_updated = datetime.datetime.utcnow().replace(tzinfo=utc) - datetime.timedelta(days=365)
        court, new = Court.objects.get_or_create(name=name, type=type, 
                    has_feed=has_feed, feed_url=feed_url, website=website,
                    last_updated=last_updated, publishes_all=publishes_all, 
                    filing_types=filing_types)
        if not new:
            print('Error, this court is already entered, possibly more than once: %s.' % name)
        elif new and not has_feed:
            print('Added this court, but it has no feed: %s - %s' % (type, name))
        else:
            print('Added this court: %s - %s' % (type, name))
    
    return None


class Command(BaseCommand):
    args = 'No args.'
    help = 'Load and update the status of each federal court RSS feed.'

    def handle(self, *args, **options):
        print(datetime.datetime.now())
        start = timer()
        
        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
    
        response = requests.get('https://pacer.uscourts.gov/file-case/court-cmecf-lookup')
        soup = BeautifulSoup(response.text, 'lxml')
        
        tbody = soup.find('tbody')
        tr_tags = tbody.find_all('tr')
        
        # Add or update courts
        with futures.ThreadPoolExecutor(max_workers=15) as executor:
            results = []
            for tag in tr_tags:
                results.append(
                    executor.submit(
                        update_court, tag
                    )
                )
            for result in futures.as_completed(results):
                try:
                    the_result = result.result(timeout=16) # Needed to trickle down exception
                except Exception as exc:
                    raise exc
        
        end = timer()
        print(end-start)