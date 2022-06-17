// Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt
/* eslint-disable 
	Author: Nghĩa+Phát
*/


frappe.require("assets/erpnext/js/ket_qua_kinh_doanh.js", function() {
	frappe.query_reports["Bang Luu Chuyen Tien Te"] = $.extend({},
		erpnext.ket_qua_kinh_doanh);

	erpnext.utils.add_dimensions('Bang Luu Chuyen Tien Te', 10);

});
