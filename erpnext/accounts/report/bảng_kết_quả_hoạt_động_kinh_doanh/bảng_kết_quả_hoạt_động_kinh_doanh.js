// Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.require("assets/erpnext/js/ketqua_kinhdoanh.js", function() {
	frappe.query_reports["Bảng Kết Quả Hoạt Động Kinh Doanh"] = $.extend({},
		erpnext.ketqua_kinhdoanh);

	erpnext.utils.add_dimensions('Bảng Kết Quả Hoạt Động Kinh Doanh', 10);
});
