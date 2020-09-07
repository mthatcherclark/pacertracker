function setCourtButtons(item, on_ready, on_checkbox, all_clicked, group_clicked) {
    //Find all the boxes that are checked and not disabled
    var checkedboxes = item.find('input[name$=\'courts\']:checked:not(:disabled)');
    //Find all the boxes that are not disabled
    var allboxes = item.find('input[name$=\'courts\']:not(:disabled)');

    //Get the 'All Courts' button in this alert
    button_item = item.find('.checkall');

    //If the 'All Courts' button should be checked
    if (checkedboxes.length == allboxes.length) {
        //If it was not clicked
        if (on_ready || on_checkbox || !all_clicked) {
            //Make sure it has the primary active classes
            button_item.addClass('btn-primary active');
        }
        //If it was clicked
        else {
            //Get rid of the active class, because this will be re-activated by the bootstrap click function
            //But add the primary class, because bootstrap won't add that
            button_item.removeClass('active').addClass('btn-primary');
        }
    }
    //If the 'All Courts' button should not be checked
    else {
        //And it wasn't clicked
        if (!all_clicked) {
            //Remove everything
            button_item.removeClass('btn-primary active');
        }
        //But if it was clicked
        else if (all_clicked) {
            //Add active, because this will be overridden by bootstrap
            //But remove primary because bootstrap won't do that.
            button_item.addClass('active').removeClass('btn-primary');
        }
    }

    //Now, for each court group
    var item_list = item.find('.checksome');

    item.find('.checksome').each(function () {
        //Get the array of court ids for that group
        var court_ids = $(this).attr('court-array').split(' ');
        //Get all the checked boxes and disabled boxes
        var checked = item.find('input[name$=\'courts\']:checked');
        
        //Set up array for the checked boxes and load it up
        var checked_ids = [];
        checked = checked.each(function(){ checked_ids.push(this.value); });
        
        //Count how many of the court group's boxes are checked
        var result = 0;
        for(var x in court_ids) {
            checker = result;
            for(var y in checked_ids) {
                if(court_ids[x] == checked_ids[y]) {
                    result++;
                }
            }
        }

        //If the group's courts are selected
        if (court_ids.length == result) {
            //And no court group was clicked
            if (on_ready || on_checkbox || all_clicked || $(this).val() != group_clicked.val()) {
                //Make sure its active and has primary
                $(this).addClass('btn-primary active');
            }
            //If this court group was clicked
            else {
                //For the one that was clicked, remove active because bootstrap
                //will over-ride and add primary
                group_clicked.removeClass('active').addClass('btn-primary');
            }
        }
        //If the group's courts are not selected
        else {
            //and this court group was not clicked
            if (on_ready || on_checkbox || all_clicked || $(this).val() != group_clicked.val()) {
                //Make sure the court group is active and primary
                $(this).removeClass('btn-primary active');
            }
            //but if this court group was clicked
            else {
                //Add active because it will be over-ridden and remove primary
                group_clicked.addClass('active').removeClass('btn-primary');
            }
        }
    
    });
    
    //Now, update the search hint and results-display if not on ready
    if (!on_ready) {
        setSearchHint(item);
    }
    
    //Finally, update the court count
    item.find('.court-count').html(checkedboxes.length);
}

function setSearchHint(alert_inner) {
    var keywords = alert_inner.find('.keywords.input-lg');
    var type_select = alert_inner.find('.type-select');
    var search_hint = alert_inner.find('.help-block.search-hint');

    var checked_courts = alert_inner.find('input[name$=\'courts\']:checked:not(:disabled)');
    var checked_ids = [];
    checked_courts.each(function(){ checked_ids.push(this.value); });
    
    if(checked_ids.length > 0 && keywords.val().length > 2) {
        search_hint.html('This search matches <a class="btn btn-default search-help-toggle"><span class="hint-count"><i class="fa fa-spinner fa-spin"></i></span> cases <i class="fa fa-question-circle icon"></i></a>')
        var query_url=keywords.attr('query-url') + '?query=' + keywords.val() + '&courts=' + checked_ids;
        if (type_select.val()) {
            query_url += '&type=' + type_select.val();
        }
        $.getJSON(query_url,function(data,status) {
            if (status=='success' && data.results.length > 0) {
                results_display = search_hint.parents('.form-group').find('.results-display');
                results_display_html = '<ul>';
                $.each(data.results, function( key, obj ) {
                    if (obj.fields.court[0] == 'D') {
                        results_display_html += '<li>' + obj.fields.court[1] + ' District Court: ' + obj.fields.title + '</li>';
                    }
                    else if (obj.fields.court[0] == 'B') {
                        results_display_html += '<li>' + obj.fields.court[1] + ' Bankruptcy Court: ' + obj.fields.title + '</li>';
                    }
                    else if (obj.fields.court[0] == 'A') {
                        results_display_html += '<li>' + obj.fields.court[1] + ' Appeals Court: ' + obj.fields.title + '</li>';
                    }
                    else {
                        results_display_html += '<li>' + obj.fields.court[1] + ': ' + obj.fields.title + '</li>';
                    }
                });
                results_display_html += '</ul>';
                results_display.html(results_display_html);
                search_hint.find('.hint-count').addClass('badge');
                search_hint.find('.hint-count').html(data.count);
            }
            else if (status=='success') {
                results_display = search_hint.parents('.form-group').find('.results-display');
                results_display.html('<em>No cases found</em>');
                search_hint.find('.hint-count').addClass('badge');
                search_hint.find('.hint-count').html(data.count);
            }
            else {
                //insert stuff to do if query is not successful here
                //or catch an empty value here
                search_hint.html('Leave blank to return all cases. <a class="btn btn-default search-help-toggle">Search tips <i class="fa fa-question-circle icon"></i></a>');
            }
        });
    }
    else {
        //Reset search-hint to default state:
        search_hint.html('Leave blank to return all cases. <a class="btn btn-default search-help-toggle">Search tips <i class="fa fa-question-circle icon"></i></a>');
        results_display.html('<em>No cases found</em>');
    }
}

$(document).ready(function () {
    //Set appropriate state for all court group buttons after load
    $('.alert-inner').each(function() {
        setCourtButtons($(this), true, false, false, false);
    });
    //Submit the form after confirming any deletions
    $('#court_form').submit(function() {
        var delete_buttons, delete_confirm;
        delete_buttons = $('.alert-delete.btn-danger');
        
        if (delete_buttons.length > 0) {
            var alert_names = [];
            delete_buttons = delete_buttons.each(function(){ alert_names.push(this.value); });
            if (alert_names.length == 1) {
                delete_confirm = confirm('Do you want to delete alert "' + alert_names[0] + '?" This will also save any alerts you changed.');
            }
            else {
                delete_confirm = confirm('Do you want to delete alerts: ' + alert_names.slice(0,-1).toString() + ' and ' + alert_names.slice(-1) + '? This will also save any alerts you changed.');
            }
            
            if (delete_confirm) {
                return true;
            }
            else {
                return false;
            }
        }
        else {
            return true;
        }
    });
    //Check/uncheck the hidden checkbox and change color of delete button when pressed
    $('.alert-delete').click(function() {
        checkbox = $(this).closest('.alert-heading').find('input[name$=\'DELETE\']');
    
        if ($(this).hasClass('active')) {
            checkbox.prop('checked', false);
            $(this).removeClass('btn-danger');
        }
        else {
            checkbox.prop('checked', true);
            $(this).addClass('btn-danger');
            if (!window.delete_info) {
                alert("Alerts selected for deletion are deleted when you click the save button.")
                window.delete_info = true
            }
        }
    });
    //Show me the court list if I ask
    var courtlist_toggle_text = $('.courtlist-toggle').first().text();
    $('.courtlist-toggle').click(function() {
        var $this = $(this);
        
        $this.first().parents('.alert-inner').find('.courts').slideToggle();
        $this.toggleClass("active");

    });
    
    $('.alert-toggle').click(function () {
        alert_body = $(this).parents('.alert').find('.alert-body');
        if (!alert_body.hasClass('in')) {
            setSearchHint($(this).parents('.alert').find('.alert-inner'));
        }
    });
    //Change accordion toggle display text when clicked
    $('.alert-body').on('hide.bs.collapse', function () {
        $(this).parents('.alert').find(".glyphicon").attr("class", "glyphicon glyphicon-chevron-right");
    });
    $('.alert-body').on('show.bs.collapse', function () {
        $(this).parents('.alert').find(".glyphicon").attr("class", "glyphicon glyphicon-chevron-down");
    });
    //Check/uncheck all courts if I ask
    $('.checkall').click(function () {
        var allboxes = $(this).parents('.alert-inner').find('input[name$=\'courts\']:not(:disabled)');

        if ($(this).hasClass('active')) {
            allboxes.prop('checked', false);
        }
        else {
            allboxes.prop('checked', true);
        }
        setCourtButtons($(this).parents('.alert-inner'), false, false, true, false);
    });
    //Check/uncheck each court group if I ask
    $('.checksome').click(function () {
        var court_ids = $(this).attr('court-array').split(' ');
        var court_selection = $(this).parents('.alert-inner');

        for(var x in court_ids){
            if($(this).hasClass('active')) {
                court_selection.find('input[value=' + court_ids[x] + '][name$=\'courts\']')
                    .prop('checked', false);
            }
            else {
                court_selection.find('input[value=' + court_ids[x] + '][name$=\'courts\']')
                    .prop('checked', true);
            }
        }

        setCourtButtons(court_selection, false, false, false, $(this));
    });
    //Set court group buttons each time a court checkbox is clicked
    $('.courtbox').click(function () {
        setCourtButtons($(this).parents('.alert-inner'), false, true, false, false);
    });
    //display the results hint when they type
    $('.keywords').typing({
        stop: function (event, $elem) {
            setSearchHint($elem.parents('.alert-inner'));
        },
        delay: 500
    });
    //Show the search help if I ask
    $('.search-box.input-prepend').on('click', '.search-help-toggle', function() {
        $(this).parents('.form-group').find('.search-help').slideToggle();
        $(this).toggleClass("active");
        
    });
    //Update search help if I change case type
    $('.type-select').change(function() {
        setSearchHint($(this).parents('.alert-inner'));
    });
});
