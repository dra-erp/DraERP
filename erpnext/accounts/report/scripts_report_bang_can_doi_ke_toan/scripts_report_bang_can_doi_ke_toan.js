// Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt
/* eslint-disable */



frappe.require("assets/erpnext/js/filterCanDoi.js", function() {
	frappe.query_reports["Scripts Report Bang Can Doi Ke Toan"] = $.extend({}, erpnext.financial_statements);

	erpnext.utils.add_dimensions('Scripts Report Bang Can Doi Ke Toan', 10);

	frappe.query_reports["Scripts Report Bang Can Doi Ke Toan"]["filters"].push({
		"fieldname": "accumulated_values",
		"label": __("Accumulated Values"),
		"fieldtype": "Check",
		"default": 1
	});

	frappe.query_reports["Scripts Report Bang Can Doi Ke Toan"]["filters"].push({
		"fieldname": "include_default_book_entries",
		"label": __("Include Default Book Entries"),
		"fieldtype": "Check",
		"default": 1
	});
});


