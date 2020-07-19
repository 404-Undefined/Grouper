from app import app, db, bcrypt, mail #from the __init__.py inside app/
from app.models import User
from app.selenium_model import get_google_meet_link
import concurrent.futures
from app.forms import RegistrationForm, LoginForm, GrouperForm, UpdateAccountForm, RequestResetForm, ResetPasswordForm, SaveGroupForm
from werkzeug.utils import secure_filename
from flask import render_template, url_for, flash, redirect, request, session
from flask_login import login_user, current_user, logout_user, login_required
from flask_mail import Message
import secrets
import os, glob
#Grouper algorithm
import random, csv
from itertools import cycle
import threading

@app.route("/")
@app.route("/home")
def home():
	return render_template("home.html")

@app.route('/register', methods=["GET", "POST"])
def register():
	if current_user.is_authenticated: #if the user is already logged in
		return redirect(url_for("home")) #redirect the user back to the home page

	form = RegistrationForm()
	if form.validate_on_submit():
		hashed_password = bcrypt.generate_password_hash(form.password.data).decode("utf-8")
		hashed_id = secrets.token_hex(8)
		user = User(email=form.email.data, password=hashed_password, user_hash=hashed_id) #pass in the UTF-8 hashed password, not the plain text nor binary
		db.session.add(user)
		db.session.commit()
		flash(f"Account created for {form.email.data}!", "success")

		#Create folders for this user
		current_working_directory = os.getcwd()
		os.mkdir(f"app/static/users/{hashed_id}")
		os.chdir(f"app/static/users/{hashed_id}")
		os.mkdir("students")
		os.mkdir("custom_groups")
		os.chdir(current_working_directory)
		return redirect(url_for("login"))
	return render_template("register.html", title="Register", form=form)


@app.route('/login', methods=["GET", "POST"])
def login():
	if current_user.is_authenticated: #if the user is already logged in
		return redirect(url_for("home")) #redirect the user back to the home page

	form = LoginForm()
	if form.validate_on_submit(): #form details are valid - email submitted, password filled in
		user = User.query.filter_by(email=form.email.data).first() #check if there are any emails within our database matching the email that the user entered
		if user and bcrypt.check_password_hash(user.password, form.password.data): #if the email exists and the password hash is valid
			login_user(user, remember=form.remember.data)

			#If the user tried to access a log-in only page and was redirected to /login, then automatically send the user back to where they were going.
			#Otherwise, redirect to the home page
			next_page = request.args.get("next")
			flash("You are logged in!", "success")
			return redirect(next_page) if next_page else redirect(url_for("home"))
		else: #login is unsuccessful
			flash("Invalid!", "danger") #danger alert (Bootstrap)
	return render_template("login.html", title="Login", form=form)

@app.route("/logout")
def logout():
	logout_user()
	return redirect(url_for("home"))


def group_function(differentiator, num_groups, student_file):
	groups = [[] for _ in range(num_groups)]
	students = []

	with open(student_file, "r") as data_file:
	    csv_reader = csv.DictReader(data_file)
	    for line in csv_reader:
	        students.append(line)

	random.shuffle(students) #shuffle students

	if differentiator == "Random":
		students_iter = iter(students)

		#first, distribute all students evenly e.g. 4 4 4 for 14 students with 3 groups
		for group in groups:
			for _ in range(len(students)//num_groups):
				group.append(next(students_iter)["Name"])

		#distribute the remaining students e.g. 5 5 4 for 14 students with 3 groups
		for i in range(len(students)%num_groups):
			groups[i].append(next(students_iter)["Name"])

		return groups


	categories = {student[differentiator] for student in students} #e.g. {Male, Female} {American, Brazilian, Spanish} {10G, 10W, 9W}

	indices = cycle(''.join(str(x) for x in range(num_groups))) #cycles through the groups e.g. 0 1 2 0 1 2 0 1 2 (if num_groups = 3)

	for category in categories:
		students_with_category = [student for student in students if student[differentiator]==category]
		for student in students_with_category:
			groups[int(next(indices))].append(student["Name"])
	return groups

def custom_group(custom_group_file):
	students = []
	with open(custom_group_file, "r") as data_file:
		csv_reader = csv.reader(data_file)
		for line in csv_reader:
			students.append(line)
	return students

def send_link_email(recipients, link, service):
	msg = Message(
		f"{service} invitation", 
		sender=app.config["MAIL_USERNAME"], 
		recipients=recipients, 
		body = f"Please join the {service} call: {link}"
	)
	mail.send(msg)

@app.route('/grouper', methods=["GET", "POST"])
def grouper():
	form = GrouperForm()

	#form.differentiator
	current_working_directory = os.getcwd()
	os.chdir(f"app/static/users/{current_user.user_hash}/custom_groups")
	custom_group_csvs = glob.glob('*.csv')
	custom_group_choices = [(custom_group, custom_group) for custom_group in custom_group_csvs]
	form.differentiator.choices = [("Random", "Random"), ("Gender", "Gender"), ("Homeroom", "Homeroom"), ("Nationality", "Nationality")] + custom_group_choices
	os.chdir(current_working_directory) #Go back to the original working directory - should be equal to os.chdir(f"../../../../../")

	#form.students
	current_working_directory = os.getcwd()
	os.chdir(f"app/static/users/{current_user.user_hash}/students")
	student_csvs = glob.glob('*.csv')
	form.students.choices = [(student_list, student_list) for student_list in student_csvs]
	os.chdir(current_working_directory) #Go back to the original working directory - should be equal to os.chdir(f"../../../../../")


	if form.validate_on_submit():
		if form.differentiator.data in ["Random", "Gender", "Homeroom", "Nationality"]:
			students_csv_path = os.path.join(app.root_path, f"static/users/{current_user.user_hash}/students", form.students.data)
			groups = group_function(form.differentiator.data, form.num_groups.data, students_csv_path)
			is_custom_group = False
		else:
			is_custom_group = True
			groups = custom_group(os.path.join(app.root_path, f"static/users/{current_user.user_hash}/custom_groups", form.differentiator.data))

		if form.service.data == "Google Meet":
			NUM_GROUPS = form.num_groups.data
			links = []
			with concurrent.futures.ThreadPoolExecutor() as executor:
			    futures = [executor.submit(get_google_meet_link, form.gmail.data, form.gmail_password.data) for _ in range(NUM_GROUPS)]

			for future in concurrent.futures.as_completed(futures):
				links.append(future.result())
			
			groups = [(groups[index], links[index]) for index in range(form.num_groups.data)]

		
		if form.send_email:
			links = [group[1] for group in groups]
			if is_custom_group:
				recipients = [group[0] for group in groups]
			else:
				recipients = []
				for group in groups:
					with open(os.path.join(app.root_path, f"static/users/{current_user.user_hash}/students", form.students.data), "r") as data_file:
						csv_reader = csv.DictReader(data_file)
						#recipients = [[line["Email"] for line in csv.DictReader(data_file) if line["Name"] in group[0]] for group in groups]
						recipients.append([line["Email"] for line in csv.DictReader(data_file) if line["Name"] in group[0]])

			flash(recipients, "info")
			flash(links, "info")
			"""
			threads = []
			for i in range(form.num_groups.data): #_ is a throw away variable - "ignore this" variable
			    t = threading.Thread(target=send_link_email, args=[recipients[i], links[i], form.service.data]) #Note: do_something, NOT do_something()
			    t.start()
			    threads.append(t)

			for thread in threads:
			    thread.join() #Make sure the thread completes before moving on because otherwise the timer wouldn't work
			"""

			#with concurrent.futures.ThreadPoolExecutor() as executor:		
			#	results = executor.map(send_link_email, recipients, links, form.service.data)
			#for result in results:
			#	print(result)
			#map(send_link_email, recipients, links, form.service.data)

			for i in range(form.num_groups.data):
				send_link_email(recipients[i], links[i], form.service.data)

		session["groups"] = groups
		return redirect(url_for("results", is_custom_group=is_custom_group))
	return render_template("grouper.html", title="Group Generator", form=form)

@app.route("/results/<int:is_custom_group>", methods=["GET", "POST"])
def results(is_custom_group):
    groups = session['groups'] # counterpart for session
    if not is_custom_group:
    	form = SaveGroupForm()

    	if form.validate_on_submit():
    		filename = form.filename.data
    		with open(f"app/static/users/{current_user.user_hash}/custom_groups/{filename}.csv", "w") as csv_file:
    			csv_writer = csv.writer(csv_file, delimiter=",")
    			for group in groups:
    				csv_writer.writerow(group)
    		flash(f"The custom group {filename} has been saved for use later!", "success")
    	return render_template("results.html", title="Results", groups=groups, form=form)
    else:
    	return render_template("results.html", title="Results", groups=groups)

@app.route("/account", methods=["GET", "POST"])
@login_required
def account():
	form = UpdateAccountForm()
	if form.validate_on_submit():
		
		#https://stackoverflow.com/questions/57641300/flasks-request-files-getlist-for-isnt-empty-when-field-is-not-submitted
		#https://stackoverflow.com/questions/58765033/multifilefield-doesnt-return-files-returns-str
		custom_group_files = request.files.getlist(form.custom_groups.name)
		if custom_group_files and all(f for f in custom_group_files):
			for custom_group_file in custom_group_files:
				custom_group_file.save(os.path.join(app.root_path, f"static/users/{current_user.user_hash}/custom_groups", custom_group_file.filename))

		class_files = request.files.getlist(form.students.name)
		if class_files and all(f for f in class_files):
			for class_file in class_files:
				class_file.save(os.path.join(app.root_path, f"static/users/{current_user.user_hash}/students", class_file.filename))

		current_user.email = form.email.data
		db.session.commit()
		flash("Your profile has been updated!", "success")
		return redirect(url_for("account"))
	elif request.method == "GET": #populate the form fields with the user's existing email
		form.email.data = current_user.email
	return render_template("account.html", title="Account", form=form)

def send_reset_email(user):
	token = user.get_reset_token()
	msg = Message(
		"Password Reset Request", 
		sender=app.config["MAIL_USERNAME"], 
		recipients=[user.email], 
		body = f"""
			To reset your password, visit the following link:
			{url_for("reset_password", token=token, _external=True)}

			If you did not make this request then simply ignore this email.
		""" #_external is to get an absolute URL instead of a relative URL
		)
	mail.send(msg)

@app.route("/reset_request", methods=["GET", "POST"])
def reset_request():
	if current_user.is_authenticated:
		return redirect(url_for("home"))	

	form = RequestResetForm()
	if form.validate_on_submit():
		user = User.query.filter_by(email=form.email.data).first()
		send_reset_email(user)
		flash("An email has been sent with instructions to reset your password.", "info")
		return redirect(url_for("login"))

	return render_template("reset_request.html", title="Reset Password", form=form)

@app.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_password(token):
	if current_user.is_authenticated:
		return redirect(url_for("home"))

	user = User.verify_reset_token(token)
	if not user:
		flash("The token is invalid or expired.", "warning")
		return redirect(url_for("reset_request"))

	form = ResetPasswordForm()
	if form.validate_on_submit():
		hashed_password = bcrypt.generate_password_hash(form.password.data).decode("utf-8")
		user.password = hashed_password
		db.session.commit()
		flash(f"Your password has been updated!", "success")
		return redirect(url_for("login"))
	return render_template("reset_password.html", title="Reset Password", form=form)