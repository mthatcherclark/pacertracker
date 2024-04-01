import datetime
import operator
import logging

from time import sleep
from collections import OrderedDict
from html2text import html2text
from optparse import make_option

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.core import mail
from django.template.loader import get_template
from django.template import Context
from django.contrib.auth.models import User
from django.conf import settings
from django.contrib.sites.models import Site

from haystack.query import SearchQuerySet

from pacertracker.models import Court, Case, Entry, Alert

utc = datetime.timezone.utc
logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Email PacerTracker live updates.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--daily',
            action='store_true',
            dest='daily',
            default=False,
            help='Send daily alerts. Only run once per day.',
        )
        
        parser.add_argument(
            '--nosend',
            action='store_true',
            dest='nosend',
            default=False,
            help='Run, but do not send the emails.'
        )


    def handle(self, *args, **options):
        messages = [] #prepare messages list
        subject, from_email = 'PACER Tracker Alert Email', 'alerts@pacertracker.com'

        time_started = datetime.datetime.utcnow().replace(tzinfo=utc)
        
        #These are used to store the time the alerts were checked (just before the query runs).
        alert_ids = []
        alert_times = {}

        #Get Queryset containing users who have alerts needing live or daily updates
        users = [alert.user for alert in Alert.objects.filter(live_updates=not(options['daily'])).distinct('user')]

        for user in users:
            if not user.is_active:
                continue

            to_email = user.email
            email_data = {}

            for alert in Alert.objects.filter(user=user, live_updates=not(options['daily'])).order_by('words'):
                #Start by filtering to cases in courts selected
                court_list = alert.courts.values_list('id', flat=True)
                cases = SearchQuerySet().models(Case).filter(court__in=court_list)

                #If there are alerts to filter by, filter by them...
                if alert.words:
                    cases = cases.filter(content=alert.words)

                #If there is a district_court_filter, apply it...
                if alert.district_court_filter:
                    cases = cases.exclude(type=alert.district_court_filter)

                #Only get cases or entries if they were captured after the last time this alert was searched.
                if alert.only_new_cases:
                    #Send alerts for any new cases in the database, even if the case wasn't just filed
                    #this is necessary because courts may not publish the typical first filing in a case, such as
                    #a complaint. Or, the first public filing after a seal is lifted may not be a complaint.
                    cases = cases.filter(captured_time__gte=alert.last_checked).order_by('type').values_list('pk', flat=True)[:160]
                    entries = Entry.objects.filter(case__in=cases)
                    cases = Case.objects.filter(id__in=cases)
                else:
                    #Updated time is set after any entries are saved. So, this will alert to any cases with entries that have
                    #been saved since the last time the alert was checked, even if the alert is checked during a trackcases run
                    cases = cases.filter(updated_time__gte=alert.last_checked).order_by('type').values_list('pk', flat=True)[:160]
                    entries = Entry.objects.filter(captured_time__gte=alert.last_checked, case__in=cases)
                    cases = Case.objects.filter(id__in=entries.values('case'))

                #If there are no cases, go to the next alert
                if not cases:
                    last_checked = datetime.datetime.utcnow().replace(tzinfo=utc)
                    alert_ids.append(alert.id)
                    alert_times['%s' % alert.id] = last_checked
                    continue

                #Add the first alert to the email_data dictionary
                email_data[str(alert.id)] = {'alert' : alert,
                                                'case_count' : cases.count(),
                                                'cases' : {}}

                #Store what will become the alert's last_checked before the query starts evaluating
                last_checked = datetime.datetime.utcnow().replace(tzinfo=utc)
                
                for case in cases.order_by('type')[:150]:

                    email_data[str(alert.id)]['cases'][str(case.id)] = {
                        'case' : case,
                        'entry_count' : entries.filter(case=case).count(),
                        'entries' : OrderedDict()
                        }

                    for entry in entries.filter(case=case).order_by('-time_filed')[:25]:
                        email_data[str(alert.id)]['cases'][str(case.id)]['entries'][str(entry.id)] = entry

                #Save the alert's id to a list and its last_checked to a dict for later updating
                alert_ids.append(alert.id)
                alert_times['%s' % alert.id] = last_checked

            if len(email_data) > 0:
                htmly = get_template('pacertracker/alert_email.html')
                
                # Get site url
                current_site = Site.objects.get_current()
                site_url = 'https://' + current_site.domain

                #Site URL is added to avoid 
                email_context = {'email_data': email_data,
                                 'site_url': site_url,
                                 'user': user}

                html_content = htmly.render(email_context)
                text_content = html2text(html_content)

                email = mail.EmailMultiAlternatives(subject, text_content, from_email, [to_email])
                email.attach_alternative(html_content, "text/html") #Send both text and html emails
                messages.append(email)

        if not(options['nosend']):
            try:
                connection = mail.get_connection() # Use default email connection
                connection.send_messages(messages)
                connection.close()
            except: #various smtplib errors
                sleep(5)
                connection = mail.get_connection() # Use default email connection
                connection.send_messages(messages)
                connection.close()
            
            for alert in Alert.objects.filter(id__in=alert_ids):
                alert.last_checked = alert_times['%s' % alert.id]
                alert.save(update_fields=['last_checked'])
                #OVERIDING THE ABOVE FOR TESTING PURPOSES 2/2
                #alert.last_checked = datetime.datetime(2015,1,12).replace(tzinfo=utc)
                #alert.save(update_fields=['last_checked'])
        else:
            print('DID NOT SEND EMAILS OR UPDATE ALERTS!')

        time_elapsed = datetime.datetime.utcnow().replace(tzinfo=utc) - time_started
        time_elapsed = str(time_elapsed).split(':')

        recipients = ''
        for message in messages:
            recipients += message.to[0] + ','
            
        final_msg = 'INFO - %s - %s sendemails took %s. Sent %s email(s) to %s.'
        final_msg = (final_msg % (time_started,
                                  'Daily' if options['daily'] else 'Live',
                                  time_elapsed[1] + ' minutes and ' + time_elapsed[2] + ' second(s)',
                                  str(len(messages)),
                                  recipients if recipients else 'no one'))
        logger.info(final_msg)
                                  

        # self.stdout.write('%s|"totals"|"%s"|%s|"%s"|"%s"' % (time_started, 'daily' if options['daily'] else 'live',
                            # str(len(messages)), 
                            # time_elapsed[1] + ' minutes and ' + time_elapsed[2] + ' second(s)',
                            # recipients))
        
