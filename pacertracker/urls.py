from django.conf.urls import url
from django.contrib.auth.views import login, password_reset
from django.contrib.auth.views import password_reset_done, password_reset_confirm
from django.contrib.auth.views import password_reset_complete

from pacertracker import views

urlpatterns = [
	url(r'^$', views.index, name='index'),
	url(r'^login/$', login, {
        'template_name': 'pacertracker/index.html'},
		name='login'),
	url(r'^logout/', views.logout_view, name='logout_view'),
	url(r'^alerts/', views.alerts, name='alerts'),
	url(r'^lookup/$', views.case_lookup, name='lookup'),
	url(r'^change_password/', views.change_password, name='change_password'),
	url(r'^password/reset/$', password_reset, 
        {'post_reset_redirect': '/password/reset/done/',
		 'template_name': 'pacertracker/password_reset_form.html',
		 'email_template_name': 'pacertracker/password_reset_email.html'},
         name='password_reset'),
    url(r'^password/reset/done/$', password_reset_done,
		{'template_name': 'pacertracker/password_reset_done.html'},
        name='password_reset_done'),
    url(r'^password/reset/(?P<uidb64>[0-9A-Za-z]+)-(?P<token>.+)/$', 
        password_reset_confirm, 
        {'post_reset_redirect' : '/password/done/',
		'template_name': 'pacertracker/password_reset_confirm.html'},
        name='password_reset_confirm'),
    url(r'^password/done/$', password_reset_complete,
		{'template_name': 'pacertracker/password_reset_complete.html'}),
]