from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import UserMixin, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField
from wtforms.validators import DataRequired
import json, os

# Create a blueprint for authentication
# auth = Blueprint('auth', __name__)

auth = Blueprint('auth', __name__, template_folder='templates', static_folder='static')

def get_users_file():
    from utils import get_file_path  # Import here so that it's called at runtime
    return get_file_path('users.json')


class User(UserMixin):
    def __init__(self, id, username, password_hash, admin=False):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self.admin = admin  # admin attribute

    @staticmethod
    def load_users():
        users_file = get_users_file()
        if not os.path.exists(users_file):
            return []
        with open(users_file, 'r', encoding='utf-8') as f:
            try:
                users_data = json.load(f)
            except json.JSONDecodeError:
                users_data = []
        return [User(
            data.get("id"),
            data.get("username"),
            data.get("password_hash"),
            data.get("admin", False)
        ) for data in users_data]

    @staticmethod
    def get_by_username(username):
        for user in User.load_users():
            if user.username == username:
                return user
        return None

    @staticmethod
    def create_user(username, password, role="user"):
        users = User.load_users()
        if any(u.username == username for u in users):
            raise ValueError("User already exists.")
        user_id = str(len(users) + 1)
        password_hash = generate_password_hash(password)
        admin_flag = True if role == "admin" else False
        new_user = User(user_id, username, password_hash, admin_flag)
        users.append(new_user)
        User.save_users(users)
        return new_user

    @staticmethod
    def save_users(users):
        users_file = get_users_file()
        with open(users_file, 'w', encoding='utf-8') as f:
            json.dump(
                [{
                    'id': user.id,
                    'username': user.username,
                    'password_hash': user.password_hash,
                    'admin': user.admin
                } for user in users],
                f, indent=4
            )


# Define Flask-WTF forms
class LoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Log In")


class RegisterForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    role = SelectField("Role", choices=[("admin", "Admin"), ("user", "User")], validators=[DataRequired()])
    submit = SubmitField("Register")


@auth.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data
        user = User.get_by_username(username)
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash("Logged in successfully.", "success")
            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard'))
        else:
            flash("Invalid username or password.", "danger")
    return render_template('login_user.html', form=form)


@auth.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if current_user.is_authenticated and current_user.admin:
        return redirect(url_for('auth.register'))
    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data
        user = User.get_by_username(username)
        if user and user.admin and check_password_hash(user.password_hash, password):
            login_user(user)
            flash("Admin logged in successfully.", "success")
            return redirect(url_for('auth.register'))
        else:
            flash("Invalid admin credentials.", "danger")
    return render_template('login_admin.html', form=form)


@auth.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Logged out successfully.", "success")
    return redirect(url_for('auth.login'))


@auth.route('/register', methods=['GET', 'POST'])
@login_required
def register():
    # Only allow registration if the current user is an admin.
    if not current_user.admin:
        flash("Unauthorized: Only admins can register new users.", "danger")
        return redirect(url_for('dashboard'))
    
    form = RegisterForm()
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data
        role = form.role.data
        try:
            User.create_user(username, password, role)
            flash("Registration successful. New user created.", "success")
            return redirect(url_for('dashboard'))
        except ValueError as ve:
            flash(str(ve), "danger")
    return render_template('register.html', form=form)


# NEW: Route to list all users (for Admin only)
@auth.route('/users')
@login_required
def list_users():
    if not current_user.admin:
        flash("Unauthorized access. Only admins can view users.", "danger")
        return redirect(url_for('dashboard'))
    users = User.load_users()
    return render_template('list_users.html', users=users)

# NEW: Route to delete a user (for Admin only)
@auth.route('/delete_user/<user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    # Only allow deletion if the current user is an admin.
    if not current_user.admin:
        flash("Unauthorized: Only admins can delete users.", "danger")
        return redirect(url_for('dashboard'))
    
    # Prevent deletion of self.
    if current_user.id == user_id:
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for('auth.list_users'))
    
    users = User.load_users()
    new_users = [u for u in users if u.id != user_id]
    if len(new_users) == len(users):
        flash("User not found.", "warning")
    else:
        User.save_users(new_users)
        flash("User deleted successfully.", "success")
    return redirect(url_for('auth.list_users'))
