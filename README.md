PACER Tracker
======================

This Django application helps reporters track federal court cases. It does so by 
downloading RSS feeds supplied by many federal courts. The frequently-updated 
feeds include many of the filings in civil, criminal, appeals and bankruptcy cases.
PACER Tracker has tracked hundreds of millions of entries in millions of cases.

PACER Tracker allows reporters to receive live or daily alerts for ongoing cases they
wish to track and alerts for cases with parties that match keywords they specify. For 
instance, a keyword of "ACME" would return any case where ACME Corp. is the primary 
plaintiff or defendant.

The app supplies a web interface for users (who are added by an admin) to setup alerts, 
change their password and setup groups of frequently-used courts.

Management Commands
===================

loadcourts - Updates information about all the federal courts, including whether they
now have a feed. It is recommended to run this once per day.

trackcases - Downloads, processes and loads data from all available RSS feeds. Should be
run as frequently as possible.

sendemails - Sends alert emails to users. Should be run as frequently as possible. The "daily"
option should be run once per day.

Logging
========

PACER Tracker produces verbose logs that can be used to track its performance and identify
any bugs. It is recommended to capture PACER Tracker logging at the INFO level in a file.

Settings
========

Specify the email address from which emails will be sent in your settings.py.

::

ALERTS_FROM_EMAIL = 'alerts@mydomain.com'

Some PACER Tracker forms use a large number of fields in its forms. An error will be generated 
unless the max number of fields check is disabled.

:: 

DATA_UPLOAD_MAX_NUMBER_FIELDS = None



