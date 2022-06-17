// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.views.calendar["IaT Maintenance Log"] = {
    field_map: {
        "start": "due_date",
        "end": "due_date",
        "id": "name",
        "title": "task",
        "allDay": "allDay",
        "progress": "progress"
    },
    filters: [
        {
            "fieldtype": "Link",
            "fieldname": "iat_name",
            "options": "IaT Maintenance",
            "label": __("IaT Maintenance")
        }
    ],
    get_events_method: "frappe.desk.calendar.get_events"
};
