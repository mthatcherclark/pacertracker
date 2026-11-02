from django.urls import re_path as url

from django.contrib.auth.views import LoginView, PasswordResetView, PasswordResetDoneView
from django.contrib.auth.views import PasswordResetCompleteView

from pacertracker import views
from pacertracker.forms import AccountPasswordResetForm

urlpatterns = [
	url(r'^$', views.index, name='index'),
	url(r'^login/$',
        LoginView.as_view(template_name='pacertracker/index.html'),
		name='login'),
	url(r'^logout/', views.logout_view, name='logout_view'),
	url(r'^alerts/', views.alerts, name='alerts'),
    url(r'^groups/', views.groups, name='groups'),
	url(r'^lookup/$', views.case_lookup, name='lookup'),
	url(r'^change_password/', views.change_password, name='change_password'),
    url(r'^users/add/$', views.add_user, name='add_user'),
    url(r'^users/$', views.manage_users, name='manage_users'),
    url(r'^account/delete/$', views.delete_account, name='delete_account'),
	url(r'^password/reset/$',
        PasswordResetView.as_view(success_url='/password/reset/done/',
            form_class=AccountPasswordResetForm,
            template_name='pacertracker/password_reset_form.html',
            email_template_name='pacertracker/password_reset_email.html',
            html_email_template_name='pacertracker/password_reset_email_body.html'),
         name='password_reset'),
    url(r'^password/reset/done/$',
        PasswordResetDoneView.as_view(template_name='pacertracker/password_reset_done.html'),
        name='password_reset_done'),
    url(r'^password/reset/(?P<uidb64>[0-9A-Za-z]+)-(?P<token>.+)/$', 
        views.AccountPasswordResetConfirmView.as_view(success_url='/password/done/',
            template_name='pacertracker/password_reset_confirm.html'),
        name='password_reset_confirm'),
    url(r'^password/done/$', 
        PasswordResetCompleteView.as_view(template_name='pacertracker/password_reset_complete.html')),
]
