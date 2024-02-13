from itertools import chain

from django.templatetags.static import static
from django import forms
from django.core.exceptions import ValidationError
from django.forms.fields import CharField
from django.forms.widgets import PasswordInput, CheckboxInput, Select
from django.forms import ModelForm, CheckboxSelectMultiple, ChoiceField
from django.contrib.auth.models import User
from django.utils.encoding import force_str
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe

from pacertracker.models import Alert, Court


def get_court_image(court):
    if court['type'] == 'D' and not court['publishes_all'] and court['has_feed']:
        return ('<i class="fa fa-institution text-danger" title="' + 
                conditional_escape(force_str(court['filing_types'])) + '"></i>')
    elif court['type'] == 'D' and not court['has_feed']:
        return '<i class="fa fa-institution court-disabled"></i>'
    elif court['type'] == 'D':
        return '<i class="fa fa-institution"></i>'
    elif court['type'] == 'B' and not court['publishes_all'] and court['has_feed']:
        return ('<i class="fa fa-usd text-danger" title="' + 
                conditional_escape(force_str(court['filing_types'])) + '"></i>')
    elif court['type'] == 'B' and not court['has_feed']:
        return '<i class="fa fa-usd court-disabled"></i>'
    elif court['type'] == 'B':
        return '<i class="fa fa-usd"></i>'


class CourtSelectMultiple(CheckboxSelectMultiple):
    def render(self, name, value, attrs=None, choices=(), renderer=None):
        #If no courts are selected for this alert, make value a blank list
        if value is None: value = []
        # Normalize values to strings so that lambda function below can check the right boxes
        str_values = set([force_str(v) for v in value])
        
        #Check to see if this form object has an id
        has_id = attrs and 'id' in attrs
        #Set up the final_attrs, which will be used in setting id for the checkbox
        final_attrs = self.build_attrs(attrs)
        
        div = "<div class='col-lg-3 col-md-4 col-sm-6 col-xs-12'>"
        
        #Start the html output
        # output = [u'<div class="row courts">']
        output = []
        
        #Start counting the field ids
        field_id = 0
        
        #Establish district and bankruptcy images
        district_img = '<i class="fa fa-institution"></i>'
        bank_img = '<i class="fa fa-usd"></i>'
        
        #Start the first column, containing district and bankruptcy courts
        # output.append(u'<div class="col-sm-4">')
        output.append(u'<div class="col-xs-12"><h4>District (' + district_img + ') and Bankruptcy Courts (' + bank_img + ')</h4></div>')
        output.append(u'<div class="col-xs-12 court-legend"><span class="text-danger" style=""><i class="fa fa-institution"></i> Courts in red</span> do not publish all of their filings. They may not alert you as soon as a new case is filed.</div>')
        output.append(u'<div class="col-xs-12 court-legend"><span class="court-disabled"><i class="fa fa-institution"></i>Courts in gray</span> do not publish any filings. They will not generate any alerts, but you can select them if you suspect this may change.</div>')
                
        #Note: there are 94 district courts and 94 bankruptcy courts.
        #So, the first column will have 47 and second will have 47.
        #has_feed, type, id, name
        courts = list(Court.objects.order_by('name', '-type').values())
        for court in courts:
            if court['type'] == 'B' or court['type'] == 'D':
                if not court['has_feed']:
                    final_attrs = dict(final_attrs, name='courts', id='%s_%s' % (attrs['id'], field_id), 
                        title='Court does not publish data.')
                    final_attrs['class'] = 'courtbox'
                else:
                    final_attrs = dict(final_attrs, name='courts', id='%s_%s' % (attrs['id'], field_id), title='')

                    if court['type'] == 'D':
                        final_attrs['class'] = 'courtbox district'
                    else:
                        final_attrs['class'] = 'courtbox'
                    
                cb = CheckboxInput(final_attrs, check_test=lambda value: value in str_values)
                rendered_cb = cb.render(name, force_str(court['id']))

                if court['type'] == 'D':
                    option_label = conditional_escape(force_str(court['name']))
                    output.append(div + u'%s %s' % (get_court_image(court), rendered_cb))
                else:
                    output.append(u' %s %s %s</div>' % (get_court_image(court), rendered_cb, option_label))
                    
                #output.append(u' %s</div>' % option_label)
                
                #If we have gone halfway through the list of district/bankruptcy courts
                #then start the next column
                if field_id == 93:
                    # output.append(u'</div>')
                    # output.append(u'<div class="col-sm-4">')
                    pass
                    
                field_id += 1
            
        # output.append(u'</div>')
        # output.append(u'<div class="col-sm-4">')
        output.append(u'<div class="col-xs-12"><h4>National Courts</h4></div>')

        for court in courts:
            if court['type'] not in ['B', 'D', 'A']:
                if not court['has_feed']:
                    final_attrs = dict(final_attrs, id='%s_%s' % (attrs['id'], field_id), 
                        title='Court does not publish data.')
                else:
                    final_attrs = dict(final_attrs, id='%s_%s' % (attrs['id'], field_id), title='')
                    
                cb = CheckboxInput(final_attrs, check_test=lambda value: value in str_values)
                rendered_cb = cb.render(name, force_str(court['id']))

                option_label = conditional_escape(force_str(court['name']))
                if not court['publishes_all'] and court['has_feed']:
                    option_label = ('<span class="text-danger" title="' + 
                                    conditional_escape(force_str(court['filing_types'])) 
                                    + '">' + option_label + '</span>')
                elif not court['has_feed']:
                    option_label = ('<span class="court-disabled" title="' +
                                    conditional_escape(force_str(court['filing_types'])) 
                                    + '">' + option_label + '</span>')
                output.append(div + u'%s %s</div>' % (rendered_cb, option_label))
                    
                field_id += 1

        output.append(u'<div class="col-xs-12"><h4>Appeals Courts</h4></div>')
            
        for court in courts:
            if court['type'] == 'A':
                if not court['has_feed']:
                    final_attrs = dict(final_attrs, id='%s_%s' % (attrs['id'], field_id), 
                        title='Court does not publish data.')
                else:
                    final_attrs = dict(final_attrs, id='%s_%s' % (attrs['id'], field_id), title='')
                    
                cb = CheckboxInput(final_attrs, check_test=lambda value: value in str_values)
                rendered_cb = cb.render(name, force_str(court['id']))

                option_label = conditional_escape(force_str(court['name']))
                if not court['publishes_all'] and court['has_feed']:
                    option_label = ('<span class="text-danger" title="' + 
                                    conditional_escape(force_str(court['filing_types'])) 
                                    + '">' + option_label + '</span>')
                elif not court['has_feed']:
                    option_label = ('<span class="court-disabled" title="' +
                                    conditional_escape(force_str(court['filing_types'])) 
                                    + '">' + option_label + '</span>')
                output.append(div + u'%s %s</div>' % (rendered_cb, option_label))
                    
                field_id += 1
        
        #Wrap up the html output
        # output.append(u'</div>')
        # output.append(u'</div>')
        return mark_safe(u'\n'.join(output))

class PasswordReset(forms.Form):
    oldpassword = forms.CharField(label='Current password:', widget=PasswordInput())
    password1 = forms.CharField(label='New password:', widget=PasswordInput())
    password2 = forms.CharField(label='Confirm new password:', widget=PasswordInput())

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super(PasswordReset, self).__init__(*args, **kwargs)

    def clean_oldpassword(self):
        if self.cleaned_data.get('oldpassword') and not self.user.check_password(self.cleaned_data['oldpassword']):
            raise forms.ValidationError('Please type your current password.')
        return self.cleaned_data['oldpassword']

    def clean_password2(self):
        if self.cleaned_data.get('password1') and self.cleaned_data.get('password2') and self.cleaned_data['password1'] != self.cleaned_data['password2']:
            raise forms.ValidationError('The new passwords are not the same.')
        return self.cleaned_data['password2']


class AlertForm(forms.ModelForm):
    district_court_filter = ChoiceField(choices=Alert.DISTRICT_FILTER, 
        widget=Select(attrs={'class': 'type-select form-control'}), required=False)

    #In case you ever want to limit the number of courts selected.
    # def clean(self):

        # if (self.cleaned_data.get('only_new_cases') == False 
            # and self.cleaned_data.get('courts').count() > 5
            # and self.cleaned_data.get('words') == ''):

            # raise ValidationError(
                # 'New filings alerts for all cases are limited to a maximum of 5 courts.'
            # )

        # return self.cleaned_data

    class Meta:
        model = Alert
        fields = "__all__"
        widgets = {
            'courts': CourtSelectMultiple(),
            'live_updates': CheckboxInput(attrs={'style': 'display:none;'}),
            'only_new_cases': CheckboxInput(attrs={'style': 'display:none;'}),
        }

