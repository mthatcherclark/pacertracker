$(document).ready(function () {
    //Submit the form after confirming any deletions
    $('#court_form').submit(function() {
        var delete_buttons, delete_confirm;
        delete_buttons = $('.alert-delete.btn-danger');
        
        if (delete_buttons.length > 0) {
            var alert_names = [];
            delete_buttons = delete_buttons.each(function(){ alert_names.push(this.value); });
            if (alert_names.length == 1) {
                delete_confirm = confirm('Do you want to delete court group "' + alert_names[0] + '?" This will also save any groups you changed.');
            }
            else {
                delete_confirm = confirm('Do you want to delete groups: ' + alert_names.slice(0,-1).toString() + ' and ' + alert_names.slice(-1) + '? This will also save any groups you changed.');
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
                alert("Court groups selected for deletion are deleted when you click the save button.")
                window.delete_info = true
            }
        }
    });
    //Change accordion toggle display text when clicked
    $('.alert-body').on('hide.bs.collapse', function () {
        $(this).parents('.alert').find(".glyphicon").attr("class", "glyphicon glyphicon-chevron-right");
    });
    $('.alert-body').on('show.bs.collapse', function () {
        $(this).parents('.alert').find(".glyphicon").attr("class", "glyphicon glyphicon-chevron-down");
    });
});
