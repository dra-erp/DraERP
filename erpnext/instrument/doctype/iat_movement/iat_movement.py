# Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document
import frappe
from frappe import _

# trọng tân fix
class IaTMovement(Document):
    def validate(self):
        self.validate_iat()
        self.validate_location()
        self.validate_employee()

    def validate_iat(self):
        for d in self.instrument:
            status, company = frappe.db.get_value("IaT", d.iat, ["status", "company"])
            if self.purpose == 'Transfer' and status in ("Draft", "Scrapped", "Sold"):
                frappe.throw(_("{0} IaT cannot be transferred").format(status))

            if company != self.company:
                frappe.throw(_("IaT {0} does not belong to company {1}").format(d.iat, self.company))

            if not (d.source_location or d.target_location or d.from_employee or d.to_employee):
                frappe.throw(_("Either location or employee must be required"))

    def validate_location(self):
        for d in self.instrument:
            if self.purpose in ['Transfer', 'Issue']:
                if not d.source_location:
                    d.source_location = frappe.db.get_value("IaT", d.iat, "location")

                if not d.source_location:
                    frappe.throw(_("Source Location is required for the IaT {0}").format(d.iat))

                if d.source_location:
                    current_location = frappe.db.get_value("IaT", d.iat, "location")

                    if current_location != d.source_location:
                        frappe.throw(_("IaT {0} does not belongs to the location {1}").
                                format(d.iat, d.source_location))

            if self.purpose == 'Issue':
                if d.target_location:
                    frappe.throw(_("Issuing cannot be done to a location. \
						Please enter employee who has issued IaT {0}").format(d.iat), title="Incorrect Movement Purpose")
                if not d.to_employee:
                    frappe.throw(_("Employee is required while issuing IaT {0}").format(d.iat))

            if self.purpose == 'Transfer':
                if d.to_employee:
                    frappe.throw(_("Transferring cannot be done to an Employee. \
						Please enter location where IaT {0} has to be transferred").format(
                                    d.iat), title="Incorrect Movement Purpose")
                if not d.target_location:
                    frappe.throw(_("Target Location is required while transferring IaT {0}").format(d.iat))
                if d.source_location == d.target_location:
                    frappe.throw(_("Source and Target Location cannot be same"))

            if self.purpose == 'Receipt':
                # only when iat is bought and first entry is made
                if not d.source_location and not (d.target_location or d.to_employee):
                    frappe.throw(_("Target Location or To Employee is required while receiving IaT {0}").format(d.iat))
                elif d.source_location:
                    # when iat is received from an employee
                    if d.target_location and not d.from_employee:
                        frappe.throw(_("From employee is required while receiving IaT {0} to a target location").format(d.iat))
                    if d.from_employee and not d.target_location:
                        frappe.throw(_("Target Location is required while receiving IaT {0} from an employee").format(d.iat))
                    if d.to_employee and d.target_location:
                        frappe.throw(_("IaT {0} cannot be received at a location and \
							given to employee in a single movement").format(d.iat))

    def validate_employee(self):
        for d in self.instrument:
            if d.from_employee:
                current_custodian = frappe.db.get_value("IaT", d.iat, "custodian")

                if current_custodian != d.from_employee:
                    frappe.throw(_("IaT {0} does not belongs to the custodian {1}").
                            format(d.iat, d.from_employee))

            if d.to_employee and frappe.db.get_value("Employee", d.to_employee, "company") != self.company:
                frappe.throw(_("Employee {0} does not belongs to the company {1}").
                                        format(d.to_employee, self.company))

    def on_submit(self):
        self.set_latest_location_in_iat()

    def on_cancel(self):
        self.set_latest_location_in_iat()

    def set_latest_location_in_iat(self):
        current_location, current_employee = '', ''
        cond = "1=1"

        for d in self.instrument:
            args = {
                    'iat': d.iat,
                    'company': self.company
            }

            # latest entry corresponds to current document's location, employee when transaction date > previous dates
            # In case of cancellation it corresponds to previous latest document's location, employee
            latest_movement_entry = frappe.db.sql(
                    """
				SELECT asm_item.target_location, asm_item.to_employee
				FROM `tabIaT Movement Item` asm_item, `tabIaT Movement` asm
				WHERE
					asm_item.parent=asm.name and
					asm_item.iat= %(iat)s and
					asm.company= %(company)s and
					asm.docstatus=1 and {0}
				ORDER BY
					asm.transaction_date desc limit 1
				""".format(cond), args)
            if latest_movement_entry:
                current_location = latest_movement_entry[0][0]
                current_employee = latest_movement_entry[0][1]

            frappe.db.set_value('IaT', d.iat, 'location', current_location)
            frappe.db.set_value('IaT', d.iat, 'custodian', current_employee)

