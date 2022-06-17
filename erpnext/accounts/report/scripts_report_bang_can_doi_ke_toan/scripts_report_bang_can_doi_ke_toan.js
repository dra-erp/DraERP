// Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt
/* eslint-disable */



frappe.require("assets/erpnext/js/filterCanDoi.js", function() {
	frappe.query_reports["Scripts Report Bang Can Doi Ke Toan"] = $.extend({}, erpnext.financial_statements);

	erpnext.utils.add_dimensions('Scripts Report Bang Can Doi Ke Toan', 10);

});


