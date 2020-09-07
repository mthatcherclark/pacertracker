from django.contrib import admin
from pacertracker.models import Alert, Court, CourtGroup, Case, Entry


class CourtAdmin(admin.ModelAdmin):
	list_display = ('name', 'type', 'has_feed','publishes_all',)
	list_filter = ('type', 'has_feed','publishes_all',)
	search_fields = ['name']
	
class CourtGroupAdmin(admin.ModelAdmin):
	filter_horizontal = ('courts',)

class CaseAdmin(admin.ModelAdmin):
	list_display = ('court','title',)
	search_fields = ['title']
	list_filter = ('court',)
	
class EntryAdmin(admin.ModelAdmin):
	list_display = ('time_filed', 'case','description',)
	search_fields = ['case','description']
	list_filter = ('case__court',)


admin.site.register(Court, CourtAdmin)
admin.site.register(CourtGroup, CourtGroupAdmin)
admin.site.register(Alert)
admin.site.register(Case, CaseAdmin)
admin.site.register(Entry, EntryAdmin)

