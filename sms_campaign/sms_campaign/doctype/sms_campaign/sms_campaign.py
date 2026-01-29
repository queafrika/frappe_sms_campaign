# Copyright (c) 2023, Finesoft Afrika and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils.safe_exec import get_safe_globals
from frappe.core.doctype.sms_settings.sms_settings import send_sms
from frappe.utils import cast

class SMSCampaign(Document):
	
	def before_insert(self):
		query_params  = frappe.get_doc("SMS Campaign Query", self.query).params
		self.params = []
		for param in query_params:
			self.append("params", {
				"label": param.label,
				"value": param.value
			})
	
	def send_non_triggered_sms(self):
		parameters = {}
		for param in self.params:
			parameters[param.label] = param.value
		self.send_sms(parameters)

	def onload(self):
		if self.trigger_type == "DIRECT" or self.trigger_type == "SCHEDULED":
			parameters = {}
			for param in self.params:
				parameters[param.label] = param.value

			query = frappe.get_doc("SMS Campaign Query", self.query)
			data = frappe.db.sql(query.query, parameters, as_dict=True)

			if len(data) < 1:
				frappe.msgprint("This query does not return any data. Therefore, no parameters and sms list will be shown.", title="No data for selected query")
				return
			
			columns = list(data[0].keys())
			self.set_onload("columns", columns)
			rows = []
			for row in data:
				row["message"] = frappe.render_template(self.message, get_context(row))
				rows.append(row)
			
			self.set_onload("rows", rows)

		else:
			parameters = {}
			doc = frappe.get_all(self.trigger_doctype, ("name"), limit=1, order_by="creation desc")[0]
			parameters[frappe.db.get_value("SMS Campaign Query", self.query, "doc_name_field")] = doc.name
			for param in self.params:
				parameters[param.label] = param.value

			query = frappe.get_doc("SMS Campaign Query", self.query)
			data = frappe.db.sql(query.query, parameters, as_dict=True)

			if len(data) < 1:
				frappe.msgprint("This query does not return any data. Therefore, no parameters and sms list will be shown.", title="No data for selected query")
				return
			
			columns = list(data[0].keys())
			self.set_onload("columns", columns)
			rows = []
			for row in data:
				row["message"] = frappe.render_template(self.message, get_context(row))
				rows.append(row)
			
			self.set_onload("rows", rows)

	def update_next_run_date(self):
		self.last_run_date = frappe.utils.nowdate()

		match self.repeats:
			case "Daily":
				self.next_run_date = frappe.utils.add_days(self.last_run_date, self.repeats_every)
			case "Weekly":
				self.next_run_date = frappe.utils.add_days(self.last_run_date, self.repeats_every * 7)	
			case "Monthly":
				self.next_run_date = frappe.utils.add_months(self.last_run_date, self.repeats_every)
			case "Yearly":
				self.next_run_date = frappe.utils.add_months(self.last_run_date, self.repeats_every * 12)

	
	def send_triggered_sms(self, doc_name):
		frappe.db.commit()
		parameters = {}
		parameters[frappe.db.get_value("SMS Campaign Query", self.query, "doc_name_field")] = doc_name
		for param in self.params:
			parameters[param.label] = param.value
		self.send_sms(parameters)

	def on_submit(self):
		if self.trigger_type == "DIRECT":
			self.send_non_triggered_sms()
		
		if self.trigger_type == "SCHEDULED":
			self.next_run_date = self.start_date
			
		self.save()

	def send_sms(self, parameters):
		query = frappe.get_doc("SMS Campaign Query", self.query)

		doctype = None
		doctype_ref = None

		if self.attachments:
			doctype = self.attachments[0].reference_doctype
			doctype_ref = self.attachments[0].reference_name_field

		if self.channel == 'SMS':
			frappe.enqueue(
				"sms_campaign.sms_campaign.queue.send_sms_queued",
				queue="default",
				timeout=4000,
				query=query,
				parameters=parameters,
				template=self.message
			)
		elif self.channel == 'Email':
			send_email(
				query=query,
				parameters=parameters,
				template=self.message,
				subject=self.email_subject,
				attachments=self.attachments,
			)
		elif self.channel == 'Whatsapp':
			send_whatsapp_message(
				query=query,
				parameters=parameters,
				template=self.message,
				subject=self.email_subject,
				doctype=doctype,
				reference_name=doctype_ref,
			)

		elif self.channel == 'Raven':
			if not self.raven_bot:
				frappe.throw("Please select a Raven Bot for this campaign.")
			try:
				send_raven_message(
					campaign=self,
					query=query,
					parameters=parameters,
					template=self.message,
					attachments=self.attachments or [],
					doctype=doctype,
					reference_name=doctype_ref,
				)
			except Exception:
				frappe.log_error(
					frappe.get_traceback(), "Raven SMS Campaign Failed"
				)

		# data = frappe.db.sql(query.query, parameters, as_dict=True)
		# for row in data:
		# 	phone = row[query.phone_field]
		# 	msg=frappe.render_template(self.message, get_context(row))
		# 	phone = format_phone_number(phone)

		# 	if phone:
		# 		receiver_list = [phone]
		# 		send_sms(receiver_list = receiver_list, msg = msg)
		# 		frappe.db.commit()
			# send_sms(receiver_list = phone, msg = msg)
						

def format_phone_number(mobile_number):
	if mobile_number is None:
		return None
	   
	if len(mobile_number) == 10:
		return "254" + mobile_number[1:]
	elif len(mobile_number) == 9:
		return "254" + mobile_number
	elif len(mobile_number) == 12:
		return "254" + mobile_number[3:]
	elif len(mobile_number) == 13:
		return "254" + mobile_number[4:]
	elif len(mobile_number) == 11:
		return "254" + mobile_number[2:]
	elif len(mobile_number) == 14:
		return "254" + mobile_number[5:]

	return None

def get_context(data):
	data["nowdate"] = frappe.utils.nowdate
	data["frappe"] = frappe._dict(utils=get_safe_globals().get("frappe").get("utils"))

	return data
	
def send_sheduled_sms():
	sms_campaigns = frappe.get_all("SMS Campaign", filters={"trigger_type": "SCHEDULED", "docstatus": 1, "active":1, "next_run_date": ["<=", frappe.utils.nowdate()]})
	for sms_campaign in sms_campaigns:
		sms_campaign = frappe.get_doc("SMS Campaign", sms_campaign.name)

		sms_campaign.send_non_triggered_sms()
		sms_campaign.update_next_run_date()

def send_triggered_after_insert_sms(doc, method=None):
	sms_campaigns = frappe.get_all("SMS Campaign", filters={"trigger_type": "TRIGGERED", "docstatus": 1, "active":1, "trigger": "New", "trigger_doctype": doc.doctype})
	for sms_campaign in sms_campaigns:
		sms_campaign = frappe.get_doc("SMS Campaign", sms_campaign.name)

		
		sms_campaign.send_triggered_sms(doc.name)

def send_triggered_on_submit_sms(doc, method=None):
	sms_campaigns = frappe.get_all("SMS Campaign", filters={"trigger_type": "TRIGGERED", "docstatus": 1, "active":1, "trigger": "Submit", "trigger_doctype": doc.doctype})
	for sms_campaign in sms_campaigns:
		sms_campaign = frappe.get_doc("SMS Campaign", sms_campaign.name)
		
		sms_campaign.send_triggered_sms(doc.name)

def send_triggered_on_cancel_sms(doc, method=None):
	sms_campaigns = frappe.get_all("SMS Campaign", filters={"trigger_type": "TRIGGERED", "docstatus": 1, "active":1, "trigger": "Cancel", "trigger_doctype": doc.doctype})
	for sms_campaign in sms_campaigns:
		sms_campaign = frappe.get_doc("SMS Campaign", sms_campaign.name)

		
		sms_campaign.send_triggered_sms(doc.name)


def send_triggered_on_update_sms(doc, method=None):
	sms_campaigns = frappe.get_all("SMS Campaign", filters={"trigger_type": "TRIGGERED", "docstatus": 1, "active":1, "trigger": "Update", "trigger_doctype": doc.doctype})
	for sms_campaign in sms_campaigns:
		sms_campaign = frappe.get_doc("SMS Campaign", sms_campaign.name)
		
		sms_campaign.send_triggered_sms(doc.name)
		

	sms_campaigns = frappe.get_all("SMS Campaign", filters={"trigger_type": "TRIGGERED", "docstatus": 1, "active":1, "trigger": "Value Change", "trigger_doctype": doc.doctype})
	for sms_campaign in sms_campaigns:
		campaign = frappe.get_doc("SMS Campaign", sms_campaign.name)
		
		if frappe.db.has_column(doc.doctype, campaign.value_changed):
			doc_before_save = doc.get_doc_before_save()
			field_value_before_save = doc_before_save.get(campaign.value_changed) if doc_before_save else None

			fieldtype = doc.meta.get_field(campaign.value_changed).fieldtype
			if cast(fieldtype, doc.get(campaign.value_changed)) == cast(fieldtype, field_value_before_save):
				# value not changed
				return
			if doc.get(campaign.value_changed) == campaign.new_value or not campaign.new_value or campaign.new_value == "":
				campaign.send_triggered_sms(doc.name)


def eval_condition(campaign):
	context = get_context(campaign)

	if campaign.condition:
		if not frappe.safe_eval(campaign.condition, None, context):
			return False
	
	return True

			
def send_email(query, parameters, template, subject, attachments):
	data = frappe.db.sql(query.query, parameters, as_dict=True)
	for row in data:
		email = row[query.recepient_field]
		bcc = row[query.bcc_emails].split(",") if query.bcc_emails else []
		cc = row[query.cc_emails].split(",") if query.cc_emails else []
		msg=frappe.render_template(template, get_context(row))
		subj = frappe.render_template(subject, get_context(row))

		attachs = []

		for att in attachments:
			if att.type == 'File':
				files = frappe.get_all("File", filters ={"file_url": row[att.file_url_field]})

				if len(files) > 0:
					file = file[0]
					file_doc = frappe.get_doc("File", file.name)


					filename = file_doc.file_name

					file_path = frappe.utils.get_site_path("", file_doc.file_url.lstrip("/"))
					with open(file_path, "rb") as file_content:
						attachs.append({"fcontent": file_content.read(), "fname": filename})
			else:
				attachs.append({frappe.attach_print(att.print_doctype, row[att.name_query_field], file_name=row[att.name_query_field])})
		
		if email:
			receiver_list = [email]
			frappe.sendmail(
				recipients=receiver_list,
				message=msg,
				subject=subj,
				cc=cc,
				bcc=bcc,
				attachments=attachs,
			)
			frappe.db.commit()

def send_whatsapp_message(query, parameters, template, doctype = None, reference_name = None):
	"""Send whatsapp message via frappe_whatsapp"""
	data = frappe.db.sql(query.query, parameters, as_dict=True)
	for row in data:
		recipient = format_phone_number(row[query.recepient_field])
		msg=frappe.render_template(template, get_context(row))
		bot = frappe.get_doc("WhatsApp Bot", query.whatsapp_bot)

		doc = frappe.get_doc({
				"doctype": "WhatsApp Message",
				"to": recipient,
				"type": "Outgoing",
				"message_type": "Manual",
				"reference_doctype": doctype,
				"reference_name": reference_name,
				"content_type": "text",
			})

		doc.save()

def _normalize(s: str) -> str:
	return (s or "").strip()

def _normalize_email(s: str) -> str:
	return (s or "").strip().lower()

def send_raven_message(campaign, query, parameters, template, attachments=None, doctype=None, reference_name=None):
	attachments = attachments or []
	data = frappe.db.sql(query.query, parameters, as_dict=True)

	bot = frappe.get_doc("Raven Bot", campaign.raven_bot)

	# Native Raven requires bot.raven_user to exist
	if not getattr(bot, "raven_user", None):
		frappe.log_error(
			f"Raven Bot {bot.name} has no raven_user linked. Open the Raven Bot and Save it once.",
			"Raven SMS Campaign - Bot Misconfigured",
		)
		return

	for row in data:
		recipient = _normalize(row.get(query.recepient_field))
		if not recipient:
			continue

		msg = frappe.render_template(template, get_context(row))

		# keep your attachment building (even if not used by RavenBot.send_message directly)
		attachs = []
		for att in attachments:
			if att.type == "File":
				files = frappe.get_all("File", filters={"file_url": row.get(att.file_url_field)})
				if files:
					f = files[0]
					file_doc = frappe.get_doc("File", f.name)
					filename = file_doc.file_name
					file_path = frappe.utils.get_site_path("", file_doc.file_url.lstrip("/"))
					with open(file_path, "rb") as file_content:
						attachs.append({"fcontent": file_content.read(), "fname": filename})
			else:
				attachs.append(
					frappe.attach_print(
						att.print_doctype,
						row.get(att.name_query_field),
						file_name=row.get(att.name_query_field),
					)
				)

		common_kwargs = dict(
			text=msg,
			markdown=True,
			link_doctype=doctype,
			link_document=reference_name,
		)

		# DM (native) — Raven creates/gets DM channel internally
		if "@" in recipient:
			user_id = _normalize_email(recipient)

			if not frappe.db.exists("User", user_id):
				frappe.log_error(f"User not found: {user_id}", "Raven SMS Campaign - Missing User")
				continue

			# ensure Raven User exists + enabled
			if not frappe.db.get_value(
				"Raven User",
				{"type": "User", "user": user_id, "enabled": 1},
				"name",
			):
				frappe.log_error(
					f"Raven User not found/disabled for: {user_id}",
					"Raven SMS Campaign - Missing Raven User",
				)
				continue

			try:
				bot.send_direct_message(user_id=user_id, **common_kwargs)
			except Exception:
				frappe.log_error(frappe.get_traceback(), f"Raven DM send failed for: {user_id}")
			continue

		try:
			bot.send_message(channel_id=recipient, **common_kwargs)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Raven Channel send failed for: {recipient}")

#def _get_raven_user_name(user_email: str) -> str | None:
	# In THE system Raven User.name == email
#	if frappe.db.exists("Raven User", user_email):
#		return user_email
#	return frappe.db.get_value("Raven User", {"type": "User", "user": user_email, "enabled": 1}, "name")

#def _get_or_create_dm_channel_id(bot_email: str, recipient_email: str) -> str:
#	bot_ru = _get_raven_user_name(bot_email)
#	rec_ru = _get_raven_user_name(recipient_email)

#	if not bot_ru:
#		frappe.throw(f"Raven User Missing/Disabled for bot user: {bot_email}")
#	if not rec_ru:
#		frappe.throw(f"Raven User Missing/Disabled for recipient: {recipient_email}")

#	existing = frappe.db.get_value(
#		"Raven Channel",
#		{
#			"is_direct_message": 1,
#			"is_archived": 0,
#
# 			"dm_user_1": ["in", [bot_ru, rec_ru]],
#			"dm_user_2": ["in", [bot_ru, rec_ru]],
#		},
#		"name",
#	)
#	if existing:
#		return existing

#	ch = frappe.get_doc({
#		"doctype": "Raven Channel",
#		"type": "Private",
#		"is_direct_message": 1,
#		"is_archived": 0,
#		"is_synced": 0,
#		"dm_user_1": bot_ru,
#		"dm_user_2": rec_ru,
#		"channel_name": f"{bot_email} _ {recipient_email}",
#	})
#	ch.insert(ignore_permissions=True)
#	return ch.name

#def send_raven_message(campaign, query, parameters, template, attachments=None, doctype=None, reference_name=None):
#	attachments = attachments or []
#	data = frappe.db.sql(query.query, parameters, as_dict=True)
#
#	bot = frappe.get_doc("Raven Bot", campaign.raven_bot)
#
#	for row in data:
#		recipient = row.get(query.recepient_field)
#		msg = frappe.render_template(template, get_context(row))
#		attachs = []
#
#		for att in attachments:
#			if att.type == "File":
#				files = frappe.get_all("File", filters={"file_url": row.get(att.file_url_field)})
#				if files:
#					file = files[0]
#					file_doc = frappe.get_doc("File", file.name)
#					filename = file_doc.file_name
#					file_path = frappe.utils.get_site_path("", file_doc.file_url.lstrip("/"))
#					with open(file_path, "rb") as file_content:
#						attachs.append({"fcontent": file_content.read(), "fname": filename})
#			else:
#				attachs.append(
#					frappe.attach_print(
#						att.print_doctype,
#						row.get(att.name_query_field),
#						file_name=row.get(att.name_query_field),
#					)
#				)
#
#		if not recipient:
#			continue
#
#		common_kwargs = dict(
#			text=msg,
#			markdown=True,
#			link_doctype=doctype,
#			link_document=reference_name,
#		)
#
#		if isinstance(recipient, str) and "@" in recipient:
#			if not frappe.db.exists("User", recipient):
#				frappe.log_error(f"User not found: {recipient}", "Raven SMS Campaign - Missing User")
#				continue
#
#			raven_user = frappe.db.get_value(
#				"Raven User",
#				{"type": "User", "user": recipient, "enabled": 1},
#				"name",
##			)
#			if not raven_user:
#				frappe.log_error(
#					f"Raven User not found or disabled for: {recipient}",
#					"Raven SMS Campaign - Missing Raven User",
#				)
#				continue
#
#			bot_email = getattr(bot, "user", None) or getattr(bot, "owner", None)
#			if not bot_email or "@" not in bot_email:
#				frappe.log_error(f"Bot email missing on Raven Bot: {bot.name}", "Raven SMS Campaign - Bot Misconfigured")
#				continue
#			dm_channel_id = _get_or_create_dm_channel_id(bot_email, recipient)
#			bot.send_message(channel_id=dm_channel_id, **common_kwargs)
##		else:
#			bot.send_message(channel_id=recipient, **common_kwargs)
