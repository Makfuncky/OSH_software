# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, make_response, abort, Response, current_app
from flask_login import LoginManager
from utils import get_file_path  # Import our shared utility function
from flask_login import login_required
import os, threading, json, csv
from datetime import datetime
from xhtml2pdf import pisa
import io
from io import BytesIO
from secure_key import secure_key as sk
from auth import auth as auth_blueprint
from auth import User
from functools import wraps
from flask import abort
from flask_login import current_user
from utils import get_file_path 


app = Flask(__name__)

app.secret_key = sk  # Ensure you use a secure key in production

# Define the directory where JSON files are stored (ensure this folder exists)
DATA_DIR = os.path.join(app.root_path, 'database')
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

#*______________________________________________________________________________ RUDIMENTARY LOCKS for concurrency
LOCKS = {
    'users.json': threading.Lock(),
    'sale_person.json': threading.Lock(),
    'customers.json': threading.Lock(),
    'products.json': threading.Lock(),
    'invoice.json': threading.Lock(),
    'suppliers.json': threading.Lock(),
    'received.json': threading.Lock()
}

def get_file_lock(filename: str) -> threading.Lock:
    """Return the lock that corresponds to the specified JSON file."""
    return LOCKS.get(filename, threading.Lock())

# ---------------
# Flask-Login Setup
# ---------------
login_manager = LoginManager()
login_manager.login_view = 'auth.login'  # This is the endpoint defined in auth.py blueprint
login_manager.init_app(app)

# Import the User class from auth.py AFTER you have defined app and initialized Flask-Login

@login_manager.user_loader
def load_user(user_id):
    users = User.load_users()
    for user in users:
        if user.id == user_id:
            return user
    return None

#*______________________________________________________________________________ Register Authentication Blueprint
app.register_blueprint(auth_blueprint)


#*______________________________________________________________________________ FLASK Index Page ROUTES
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')


#*______________________________________________________________________________ Input Sanitization
def sanitize_string(value: str) -> str:
    if not value:
        return ""
    # Minimal sanitization: strip and remove newlines
    return value.strip().replace("\n", " ").replace("\r", " ")


#*______________________________________________________________________________ SUPPLIER FUNCTIONS
class Supplier:
    def __init__(self, supplier_s_no, supplier_name, contact_person, supplier_type, address, contact_number):
        self.supplier_s_no = supplier_s_no
        self.supplier_name = supplier_name
        self.contact_person = contact_person
        self.supplier_type = supplier_type
        self.address = address
        self.contact_number = contact_number

    @staticmethod
    def load_suppliers_from_json():
        file_path = get_file_path('suppliers.json')
        lock = get_file_lock('suppliers.json')
        with lock:
            if not os.path.exists(file_path):
                return []
            with open(file_path, 'r', encoding='utf-8') as file:
                try:
                    suppliers = json.load(file)
                except json.JSONDecodeError:
                    suppliers = []
        return [Supplier(**supplier) for supplier in suppliers]

    @staticmethod
    def save_suppliers_to_json(suppliers):
        file_path = get_file_path('suppliers.json')
        lock = get_file_lock('suppliers.json')
        with lock:
            with open(file_path, 'w', encoding='utf-8') as file:
                json.dump([supplier.__dict__ for supplier in suppliers], file, indent=4)

    @staticmethod
    def save_supplier_to_json(supplier_data):
        suppliers = Supplier.load_suppliers_from_json()
        # Duplicate check by supplier_s_no:
        if any(s.supplier_s_no == supplier_data["supplier_s_no"] for s in suppliers):
            raise ValueError("Duplicate supplier_s_no detected.")
        suppliers.append(Supplier(**supplier_data))
        Supplier.save_suppliers_to_json(suppliers)

def get_last_supplier_number_db():
    suppliers = Supplier.load_suppliers_from_json()
    if not suppliers:
        return None
    try:
        last_supplier = max(suppliers, key=lambda s: int(s.supplier_s_no.split('_')[1]))
        return last_supplier.supplier_s_no
    except (ValueError, IndexError):
        return None

def generate_new_supplier_number(last_supplier_number):
    if not last_supplier_number or '_' not in last_supplier_number:
        return "S_0001"
    try:
        prefix, num = last_supplier_number.split('_')
        new_num = int(num) + 1
        return f"{prefix}_{new_num:04d}"
    except ValueError:
        return "S_0001"

# Add Supplier
@app.route('/add_supplier', methods=['GET', 'POST'])
def add_supplier():
    if request.method == 'POST':
        supplier_data = [
            request.form.get('supplier_s_no'),
            request.form.get('supplier_name'),
            request.form.get('contact_person'),
            request.form.get('supplier_type'),
            request.form.get('address'),
            request.form.get('contact_number')
        ]
        # You might require at least supplier_s_no and supplier_name.
        if not supplier_data[0] or not supplier_data[1]:
            flash("Please fill out all required fields!", "warning")
            return redirect(url_for('add_supplier'))
        try:
            Supplier.save_supplier_to_json({
                "supplier_s_no": supplier_data[0],
                "supplier_name": supplier_data[1],
                "contact_person": supplier_data[2],
                "supplier_type": supplier_data[3],
                "address": supplier_data[4],
                "contact_number": supplier_data[5]
            })
            flash("Supplier added successfully!", "success")
            return redirect(url_for('list_suppliers'))
        except Exception as e:
            flash("Error adding supplier: " + str(e), "danger")
            return redirect(url_for('add_supplier'))
    
    last_supplier_number = get_last_supplier_number_db()
    new_supplier_number = generate_new_supplier_number(last_supplier_number)
    return render_template('add_supplier.html', new_supplier_number=new_supplier_number)

# List Suppliers
@app.route('/list_suppliers')
def list_suppliers():
    suppliers = Supplier.load_suppliers_from_json()
    return render_template('list_suppliers.html', suppliers=suppliers)

# Download Suppliers CSV
@app.route('/download_suppliers')
def download_suppliers():
    suppliers = Supplier.load_suppliers_from_json()
    si = io.StringIO()
    csv_writer = csv.writer(si)
    csv_writer.writerow(["supplier_s_no", "supplier_name", "contact_person", "supplier_type", "address", "contact_number"])
    for sup in suppliers:
        csv_writer.writerow([sup.supplier_s_no, sup.supplier_name, sup.contact_person, sup.supplier_type, sup.address, sup.contact_number])
    output = si.getvalue()
    return Response(output, mimetype="text/csv", headers={"Content-disposition": "attachment; filename=suppliers.csv"})

# Upload Suppliers CSV
@app.route('/upload_suppliers', methods=['GET', 'POST'])
def upload_suppliers():
    if request.method == 'POST':
        file = request.files.get('file')
        if not file:
            flash("No file selected", "warning")
            return redirect(url_for('upload_suppliers'))
        if not file.filename.endswith('.csv'):
            flash("Only CSV files are allowed", "warning")
            return redirect(url_for('upload_suppliers'))
        
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_input = csv.DictReader(stream)
        inserted = 0
        skipped = 0
        new_suppliers = []
        for row in csv_input:
            supplier_data = {
                "supplier_s_no": row.get("supplier_s_no", "").strip(),
                "supplier_name": row.get("supplier_name", "").strip(),
                "contact_person": row.get("contact_person", "").strip(),
                "supplier_type": row.get("supplier_type", "").strip(),
                "address": row.get("address", "").strip(),
                "contact_number": row.get("contact_number", "").strip()
            }
            if not supplier_data["supplier_s_no"] or not supplier_data["supplier_name"]:
                skipped += 1
                continue
            new_suppliers.append(supplier_data)
            inserted += 1
        
        # Load existing suppliers and check for duplicates.
        existing_suppliers = Supplier.load_suppliers_from_json()
        existing_ids = {sup.supplier_s_no for sup in existing_suppliers}
        for sup_data in new_suppliers:
            if sup_data["supplier_s_no"] in existing_ids:
                continue
            try:
                Supplier.save_supplier_to_json(sup_data)
            except Exception as e:
                skipped += 1
        flash(f"CSV Upload complete. Inserted: {inserted}, Skipped: {skipped}", "success")
        return redirect(url_for('list_suppliers'))
    
    return render_template('upload_suppliers.html')


#*______________________________________________________________________________ Customer Functions
class Customer:
    def __init__(
        self, 
        customer_s_no, 
        customer_name, 
        sales_person, 
        address, 
        vat_no, 
        credit_term, 
        contact_person, 
        contact_number, 
        company_registration_no
    ):
        self.customer_s_no = customer_s_no
        self.customer_name = customer_name
        self.sales_person = sales_person
        self.address = address
        self.vat_no = vat_no
        self.credit_term = credit_term
        self.contact_person = contact_person
        self.contact_number = contact_number
        self.company_registration_no = company_registration_no

    @staticmethod
    def load_customers_from_json():
        file_path = get_file_path('customers.json')
        lock = get_file_lock('customers.json')
        with lock:
            if not os.path.exists(file_path):
                return []
            with open(file_path, 'r', encoding='utf-8') as file:
                try:
                    customers = json.load(file)
                except json.JSONDecodeError:
                    customers = []
        return [Customer(**customer) for customer in customers]

    @staticmethod
    def save_customers_to_json(customers):
        file_path = get_file_path('customers.json')
        lock = get_file_lock('customers.json')
        with lock:
            with open(file_path, 'w', encoding='utf-8') as file:
                json.dump([customer.__dict__ for customer in customers], file, indent=4)

    @staticmethod
    def save_customer_to_json(customer_data):
        # Duplicate check by customer_s_no (this should not trigger if a new code is generated)
        customers = Customer.load_customers_from_json()
        if any(c.customer_s_no == customer_data["customer_s_no"] for c in customers):
            raise ValueError("Duplicate customer_s_no detected.")
        customers.append(Customer(**customer_data))
        Customer.save_customers_to_json(customers)

def get_last_customer_number_db():
    customers = Customer.load_customers_from_json()
    if not customers:
        return None
    try:
        last_customer = max(customers, key=lambda c: int(c.customer_s_no.split('_')[1]))
        return last_customer.customer_s_no
    except (ValueError, IndexError):
        return None

def generate_new_customer_number(last_customer_number):
    """Generates a new customer number (e.g., C_0001)."""
    if not last_customer_number or '_' not in last_customer_number:
        return "C_0001"
    try:
        prefix, num = last_customer_number.split('_')
        new_num = int(num) + 1
        return f"{prefix}_{new_num:04d}"
    except ValueError:
        return "C_0001"

def save_customer_to_db(customer_data):
    safe_data = [sanitize_string(x) for x in customer_data]
    try:
        Customer.save_customer_to_json({
            'customer_s_no': safe_data[0],
            'customer_name': safe_data[1],
            'sales_person': safe_data[2],
            'address': safe_data[3],
            'vat_no': safe_data[4],
            'credit_term': safe_data[5],
            'contact_person': safe_data[6],
            'contact_number': safe_data[7],
            'company_registration_no': safe_data[8]
        })
        return True
    except Exception as e:
        print(f"Error saving customer: {e}")
        return False

def load_sale_persons():
    # Build the file path for database/sale_person.json
    file_path = os.path.join(current_app.root_path, 'database', 'sale_person.json')
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            data = json.load(file)
            current_app.logger.info("Loaded sale_person.json: %s", data)
            # Ensure your JSON has the key 'sale_persons'
            return data.get('sale_persons', [])
    except Exception as e:
        current_app.logger.error("Error loading sale_person.json: %s", e)
        return []

@app.route('/add_customer', methods=['GET', 'POST'])
def add_customer():
    if request.method == 'POST':
        # Always generate a new customer code on form submission.
        new_customer_number = generate_new_customer_number(get_last_customer_number_db())
        customer_data = [
            new_customer_number,  # Use the newly generated code
            request.form.get('customer_name'),
            request.form.get('sales_person'),
            request.form.get('address'),
            request.form.get('vat_no'),
            request.form.get('credit_term'),
            request.form.get('contact_person'),
            request.form.get('contact_number'),
            request.form.get('company_registration_no')
        ]

        # Check that all fields (except auto-generated code) are provided.
        if not all(customer_data[1:]):
            flash("Please fill out all fields!", "warning")
            return redirect(url_for('add_customer'))
        else:
            if save_customer_to_db(customer_data):
                flash("Customer added successfully!", "success")
                return redirect(url_for('success'))
            else:
                flash("Error adding customer, please try again", "danger")
                return redirect(url_for('add_customer'))

    # For GET requests, generate a new customer number and load sale persons.
    new_customer_number = generate_new_customer_number(get_last_customer_number_db())
    sale_persons = load_sale_persons()
    current_app.logger.info("Sale persons passed to template: %s", sale_persons)
    return render_template('add_customer.html', new_customer_number=new_customer_number, sale_persons=sale_persons)


#*______________________________________________________________________________ NEW: List Customers, Download CSV & Upload CSV
@app.route('/list_customers')
def list_customers():
    """
    Render a page that displays all customers in a table.
    """
    customers = Customer.load_customers_from_json()
    return render_template('list_customers.html', customers=customers)

@app.route('/download_customers')
def download_customers():
    """
    Convert the customer list into a CSV file and return it for download.
    """
    customers = Customer.load_customers_from_json()
    # Use StringIO to build CSV data in memory.
    si = io.StringIO()
    csv_writer = csv.writer(si)
    
    # Write header row
    csv_writer.writerow([
        "customer_s_no", "customer_name", "sales_person", "address", 
        "vat_no", "credit_term", "contact_person", "contact_number", "company_registration_no"
    ])
    
    # Write customer rows
    for cust in customers:
        csv_writer.writerow([
            cust.customer_s_no, cust.customer_name, cust.sales_person, cust.address,
            cust.vat_no, cust.credit_term, cust.contact_person, cust.contact_number,
            cust.company_registration_no
        ])
    
    output = si.getvalue()
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=customers.csv"}
    )

@app.route('/upload_customers', methods=['GET', 'POST'])
def upload_customers():
    """
    Provides a form to upload a CSV file. On POST, reads the CSV file and 
    adds new customers (each with an auto-generated customer code).
    """
    if request.method == 'POST':
        file = request.files.get('file')
        if not file:
            flash("No file selected", "warning")
            return redirect(url_for('upload_customers'))
        if not file.filename.endswith('.csv'):
            flash("Only CSV files are allowed", "warning")
            return redirect(url_for('upload_customers'))
        
        # Read CSV file as a UTF-8 decoded stream.
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_input = csv.DictReader(stream)
        inserted = 0
        skipped = 0
        
        # Process each row in the CSV.
        for row in csv_input:
            # Generate a new customer code for this row.
            new_customer_number = generate_new_customer_number(get_last_customer_number_db())
            # Expect CSV columns to be named exactly as follows:
            # customer_name, sales_person, address, vat_no, credit_term, contact_person, contact_number, company_registration_no
            customer_data = [
                new_customer_number,  # Auto-generated new code.
                row.get("customer_name", ""),
                row.get("sales_person", ""),
                row.get("address", ""),
                row.get("vat_no", ""),
                row.get("credit_term", ""),
                row.get("contact_person", ""),
                row.get("contact_number", ""),
                row.get("company_registration_no", "")
            ]
            # Skip the row if any required field (except the auto-generated code) is missing.
            if not all(customer_data[1:]):
                skipped += 1
                continue
            if save_customer_to_db(customer_data):
                inserted += 1
            else:
                skipped += 1
        
        flash(f"CSV Upload complete. Inserted: {inserted}, Skipped: {skipped}", "success")
        return redirect(url_for('list_customers'))
    
    # GET: Render the upload form.
    return render_template('upload_customers.html')


#*______________________________________________________________________________ Customer Ledger



class CustomerLedgerProcessor:
    def __init__(self, customer_list):
        # customer_list should be a list of dicts with keys "code" and "name"
        self.customer_list = customer_list

    def get_selected_customer(self, customer_code, customer_name):
        """
        Returns the customer dict (from self.customer_list) matching either
        the customer code or the customer name.
        """
        for cust in self.customer_list:
            if customer_code and cust["code"] == customer_code:
                return cust
            if customer_name and cust["name"] == customer_name:
                return cust
        return None

    def parse_date_range(self, start_date_str, end_date_str):
        """
        Parses start and end dates from strings. Invoice dates (in invoice.json)
        are assumed to be in format "07-Dec-24" (day-monthAbbr-year) while payment
        dates (in received.json) are in "YYYY-MM-DD".
        """
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
            return start_date, end_date
        except Exception as e:
            return None, None

    def fetch_invoices(self, customer_name, start_date, end_date):
        """
        Load invoices from invoice.json, filter for the given customer_name and date range.
        For each matching invoice, build a ledger entry with:
            - date, description (invoice_number), type "Invoice",
              credit = sum(net_amount of items), debit = 0.
        """
        ledger_entries = []
        invoice_file = get_file_path('invoice.json')
        if not os.path.exists(invoice_file):
            return ledger_entries

        with open(invoice_file, 'r', encoding='utf-8') as f:
            try:
                invoices = json.load(f)
            except json.JSONDecodeError:
                invoices = []

        for inv in invoices:
            # Compare customer name (trimmed)
            if inv.get("customer_name", "").strip() != customer_name.strip():
                continue
            try:
                # Parse invoice date – expected format "07-Dec-24"
                inv_date = datetime.strptime(inv.get("date", "").strip(), "%d-%b-%y")
            except Exception:
                continue

            if not (start_date <= inv_date <= end_date):
                continue

            # Sum the net amounts in the invoice items.
            try:
                credit_amount = round(sum(float(item.get('net_amount', 0)) for item in inv.get("items", [])), 3)
            except Exception:
                credit_amount = 0.0

            ledger_entries.append({
                "date": inv_date,
                "description": inv.get("invoice_number", ""),
                "type": "Invoice",
                "debit": 0.0,
                "credit": credit_amount
            })
        return ledger_entries

    def fetch_payments(self, customer_name, start_date, end_date):
        """
        Load payments from received.json. For each payment record,
        check allocations and for each allocation matching the customer_name,
        create a ledger entry with:
            - date (from payment.received_date),
            - description: "Payment for {invoice_number}",
            - type "Payment",
            - debit = amount_againts_invoice, credit = 0.
        """
        ledger_entries = []
        payments_file = get_file_path('received.json')
        if not os.path.exists(payments_file):
            return ledger_entries

        with open(payments_file, 'r', encoding='utf-8') as f:
            try:
                payments = json.load(f)
            except json.JSONDecodeError:
                payments = []

        for payment in payments:
            try:
                pay_date = datetime.strptime(payment.get("received_date", "").strip(), "%Y-%m-%d")
            except Exception:
                continue

            if not (start_date <= pay_date <= end_date):
                continue

            for alloc in payment.get("allocations", []):
                if alloc.get("custoemr_name", "").strip() != customer_name.strip():
                    continue
                try:
                    debit_amount = round(float(alloc.get("amount_againts_invoice", 0)), 3)
                except Exception:
                    debit_amount = 0.0

                ledger_entries.append({
                    "date": pay_date,
                    "description": "Payment for " + alloc.get("invoice_number", ""),
                    "type": "Payment",
                    "debit": debit_amount,
                    "credit": 0.0
                })
        return ledger_entries

    def build_ledger(self, invoice_entries, payment_entries):
        """
        Merge the invoice and payment entries, sort by date (and time if available)
        and calculate a running balance.
        Balance is computed as:
            running_balance += (credit - debit)
        Each entry is augmented with a serial number (sno) and a formatted date string.
        """
        all_entries = invoice_entries + payment_entries
        if not all_entries:
            return []

        # Sort by date (ascending)
        all_entries.sort(key=lambda x: x["date"])

        running_balance = 0.0
        ledger = []
        for idx, entry in enumerate(all_entries, start=1):
            running_balance += entry["credit"] - entry["debit"]
            entry["sno"] = idx
            entry["balance"] = round(running_balance, 3)
            entry["date_str"] = entry["date"].strftime("%Y-%m-%d")
            ledger.append(entry)
        return ledger

    def process_ledger(self, customer_code, customer_name, start_date_str, end_date_str):
        """
        Master function that uses all the functions above:
          - determines the customer,
          - parses the dates,
          - fetches invoices and payments,
          - builds and returns the ledger.
        Returns (ledger, error_message). If no ledger entries found,
        error_message contains "Customer Not Found."
        """
        selected = self.get_selected_customer(customer_code, customer_name)
        if not selected:
            return None, "Customer Not Found."

        start_date, end_date = self.parse_date_range(start_date_str, end_date_str)
        if not start_date or not end_date:
            return None, "Invalid date range."

        # Use the customer name from the selected customer record
        cust_name = selected["name"]

        invoice_entries = self.fetch_invoices(cust_name, start_date, end_date)
        payment_entries = self.fetch_payments(cust_name, start_date, end_date)
        ledger = self.build_ledger(invoice_entries, payment_entries)

        if not ledger:
            return None, "Customer Not Found."
        return ledger, ""


@app.route('/customer_ledger', methods=['GET', 'POST'])
def customer_ledger():
    # Load customer list from customers.json
    customers_file = get_file_path('customers.json')
    customer_list = []
    if os.path.exists(customers_file):
        with open(customers_file, 'r', encoding='utf-8') as f:
            try:
                cust_data = json.load(f)
                for c in cust_data:
                    customer_list.append({
                        "code": c.get("customer_s_no", "").strip(),
                        "name": c.get("customer_name", "").strip()
                    })
            except json.JSONDecodeError:
                customer_list = []
    
    ledger = None
    message = ""
    customer_code = request.form.get("customer_code", "")
    customer_name = request.form.get("customer_name", "")
    start_date = request.form.get("start_date", "")
    end_date = request.form.get("end_date", "")
    
    if request.method == "POST" and start_date and end_date:
        processor = CustomerLedgerProcessor(customer_list)
        ledger, message = processor.process_ledger(customer_code, customer_name, start_date, end_date)
    
    # Optionally, you can pass today's date if you want server-side default for the start_date field.
    today = datetime.today().strftime("%Y-%m-%d")
    
    return render_template("customer_ledger.html",
                           customer_list=customer_list,
                           customer_code=customer_code,
                           customer_name=customer_name,
                           start_date=start_date,
                           today_date=today,
                           ledger=ledger,
                           message=message)


#*______________________________________________________________________________ Product Functions
class Product:
    def __init__(self, product_s_no, product_name, rate, vat_check, declaration_number, release_date, quantity, customs_duty, vat_value, other_cost, supplier_name, 
                 supplier_invoice_no, country, invoice_date, invoice_value, shipping_agent_name, shipping_invoice_no, shipping_invoice_date, shipping_invoice_value, declared_value=0.0):
        self.product_s_no = product_s_no
        self.product_name = product_name
        self.rate = rate
        self.vat_check = vat_check
        self.declaration_number = declaration_number
        self.release_date = release_date
        self.quantity = quantity
        self.customs_duty = customs_duty
        self.vat_value = vat_value
        self.other_cost = other_cost
        self.declared_value = float(declared_value or 0.0)
        self.supplier_name = supplier_name
        self.supplier_invoice_no = supplier_invoice_no
        self.country = country
        self.invoice_date = invoice_date
        self.invoice_value = invoice_value
        self.shipping_agent_name = shipping_agent_name
        self.shipping_invoice_no = shipping_invoice_no
        self.shipping_invoice_date = shipping_invoice_date
        self.shipping_invoice_value = shipping_invoice_value

    @staticmethod
    def load_products_from_json():
        file_path = get_file_path('products.json')
        lock = get_file_lock('products.json')
        with lock:
            if not os.path.exists(file_path):
                return []
            with open(file_path, 'r', encoding='utf-8') as file:
                try:
                    products = json.load(file)
                except json.JSONDecodeError:
                    products = []
        product_objects = []
        for p in products:
            valid_keys = Product.__init__.__code__.co_varnames[1:]
            filtered_p = {k: p[k] for k in p if k in valid_keys}
            product_objects.append(Product(**filtered_p))
        return product_objects

    @staticmethod
    def save_products_to_json(products):
        file_path = get_file_path('products.json')
        lock = get_file_lock('products.json')
        with lock:
            with open(file_path, 'w', encoding='utf-8') as file:
                json.dump([product.__dict__ for product in products], file, indent=4)
        print("[DEBUG] Saved", len(products), "products to file:", file_path)

    @staticmethod
    def save_product_to_json(product_data):
        """
        Always append a new product record.
        """
        products = Product.load_products_from_json()
        products.append(Product(**product_data))
        print("[DEBUG] Added new product purchase:", product_data["product_s_no"])
        Product.save_products_to_json(products)
        print("[DEBUG] Total products:", len(products))

def get_last_product_number_db():
    products = Product.load_products_from_json()
    if not products:
        return None
    try:
        last_product = max(products, key=lambda p: int(p.product_s_no.split('_')[1]))
        return last_product.product_s_no
    except (ValueError, IndexError):
        return None

def generate_new_product_number(last_product_number):
    if not last_product_number or '_' not in last_product_number:
        return "P_0001"
    try:
        prefix, num = last_product_number.split('_')
        new_num = int(num) + 1
        return f"{prefix}_{new_num:04d}"
    except ValueError:
        return "P_0001"

@app.route('/add_product', methods=['GET', 'POST'])
def add_product():
    if request.method == 'POST':
        product_type = request.form.get('product_type')
        if product_type == 'existing':
            # Get the product S.No set by JavaScript
            product_s_no = request.form.get('product_s_no')
            # Look up the product name from products.json to ensure it matches what is stored
            existing_products_list = Product.load_products_from_json()
            matching_product = None
            for prod in existing_products_list:
                if prod.product_s_no == product_s_no:
                    matching_product = prod
                    break
            if matching_product:
                product_name = matching_product.product_name
            else:
                # Fallback in case the product is not found
                product_name = request.form.get('existing_product_name') or ""
        else:
            # For a new product, get the product name from the text input.
            product_name = request.form.get('new_product_name') or ""
            last_product_number = get_last_product_number_db()
            product_s_no = generate_new_product_number(last_product_number)

        # Convert numeric fields to float with 3 decimals; Quantity also as float.
        try:
            rate = round(float(request.form.get('rate') or 0), 3)
        except:
            rate = 0.0
        try:
            quantity = round(float(request.form.get('quantity') or 0), 3)
        except:
            quantity = 0.0
        try:
            customs_duty = round(float(request.form.get('customs_duty') or 0), 3)
        except:
            customs_duty = 0.0
        try:
            vat_value = round(float(request.form.get('vat_value') or 0), 3)
        except:
            vat_value = 0.0
        try:
            other_cost = round(float(request.form.get('other_cost') or 0), 3)
        except:
            other_cost = 0.0
        try:
            declared_value = round(float(request.form.get('declared_value') or 0), 3)
        except:
            declared_value = 0.0
        try:
            invoice_value = round(float(request.form.get('invoice_value') or 0), 3)
        except:
            invoice_value = 0.0
        try:
            shipping_invoice_value = round(float(request.form.get('shipping_invoice_value') or 0), 3)
        except:
            shipping_invoice_value = 0.0

        # Build the product_data list with strings for numeric values.
        product_data = [
            product_s_no,
            product_name,
            str(rate),
            'Yes' if request.form.get('vat_check') else 'No',
            request.form.get('declaration_number'),
            request.form.get('release_date'),
            str(quantity),
            str(customs_duty),
            str(vat_value),
            str(other_cost),
            str(declared_value),
            request.form.get('supplier_name'),
            request.form.get('supplier_invoice_no'),
            request.form.get('country'),
            request.form.get('invoice_date'),
            str(invoice_value),
            request.form.get('shipping_agent_name'),
            request.form.get('shipping_invoice_no'),
            request.form.get('shipping_invoice_date'),
            str(shipping_invoice_value)
        ]

        print("[DEBUG] Raw product_data from form:", product_data)

        # Require that S.No, Product Name, and Rate are provided.
        if not product_data[0] or not product_data[1] or not product_data[2]:
            flash("Product S.No, Product Name, and Rate are required!", "warning")
            return redirect(url_for('add_product'))

        try:
            if save_product_to_db(product_data):
                flash("Product saved successfully!", "success")
                return redirect(url_for('success'))
            else:
                flash("Error adding product to database", "danger")
                return redirect(url_for('add_product'))
        except Exception as e:
            flash(f"Error: {e}", "danger")
            print("[ERROR] Exception in POST /add_product:", e)
            return redirect(url_for('add_product'))

    # GET: Prepare data for rendering the form.
    products = Product.load_products_from_json()
    unique_products = {}
    for p in products:
        key = p.product_name if p.product_name.strip() != "" else p.product_s_no
        if key not in unique_products:
            unique_products[key] = p
    existing_products = list(unique_products.values())

    try:
        suppliers = Supplier.load_suppliers_from_json()
    except Exception:
        suppliers = []
    purchase_suppliers = [s.supplier_name for s in suppliers if s.supplier_type.lower() == "purchase"] if suppliers else []
    shipping_suppliers = [s.supplier_name for s in suppliers if s.supplier_type.lower() == "shipping"] if suppliers else []

    last_product_number = get_last_product_number_db()
    new_product_number = generate_new_product_number(last_product_number)

    print("[DEBUG] Rendering form with new_product_number:", new_product_number)
    return render_template(
        'add_product.html',
        existing_products=existing_products,
        purchase_suppliers=purchase_suppliers,
        shipping_suppliers=shipping_suppliers,
        new_product_number=new_product_number,
        datetime=datetime
    )

def save_product_to_db(product_data):
    sanitized = [sanitize_string(str(x)) for x in product_data]
    print("[DEBUG] Sanitized product_data:", sanitized)
    try:
        data_dict = {
            'product_s_no': sanitized[0],
            'product_name': sanitized[1],
            'rate': round(float(sanitized[2] or 0), 3),
            'vat_check': sanitized[3],
            'declaration_number': sanitized[4],
            'release_date': sanitized[5],
            'quantity': round(float(sanitized[6] or 0), 3),
            'customs_duty': round(float(sanitized[7] or 0), 3),
            'vat_value': round(float(sanitized[8] or 0), 3),
            'other_cost': round(float(sanitized[9] or 0), 3),
            'declared_value': round(float(sanitized[10] or 0), 3),
            'supplier_name': sanitized[11],
            'supplier_invoice_no': sanitized[12],
            'country': sanitized[13],
            'invoice_date': sanitized[14],
            'invoice_value': round(float(sanitized[15] or 0), 3),
            'shipping_agent_name': sanitized[16],
            'shipping_invoice_no': sanitized[17],
            'shipping_invoice_date': sanitized[18],
            'shipping_invoice_value': round(float(sanitized[19] or 0), 3)
        }
        print("[DEBUG] Data dictionary to be saved:", data_dict)
        Product.save_product_to_json(data_dict)
        print("[DEBUG] Product saved successfully in save_product_to_db!")
        return True
    except ValueError as ve:
        print("[ERROR] ValueError in save_product_to_db:", ve)
        return False
    except Exception as e:
        print("[ERROR] Exception in save_product_to_db:", e)
        return False


#*______________________________________________________________________________ Product CSV Functionality

@app.route('/list_products')
def list_products():
    """Render a page that displays all products in a table."""
    products = Product.load_products_from_json()
    return render_template('list_products.html', products=products)

@app.route('/download_products')
def download_products():
    """Convert the product list into a CSV file and return it for download."""
    products = Product.load_products_from_json()
    si = io.StringIO()
    csv_writer = csv.writer(si)
    
    # Write header row
    csv_writer.writerow([
        "product_s_no", "product_name", "rate", "vat_check", "declaration_number",
        "release_date", "quantity", "customs_duty", "vat_value", "other_cost", 
        "declared_value", "supplier_name", "supplier_invoice_no", "country", 
        "invoice_date", "invoice_value", "shipping_agent_name", "shipping_invoice_no",
        "shipping_invoice_date", "shipping_invoice_value"
    ])
    
    # Write product rows
    for prod in products:
        csv_writer.writerow([
            prod.product_s_no,
            prod.product_name,
            prod.rate,
            prod.vat_check,
            prod.declaration_number,
            prod.release_date,
            prod.quantity,
            prod.customs_duty,
            prod.vat_value,
            prod.other_cost,
            prod.declared_value,
            prod.supplier_name,
            prod.supplier_invoice_no,
            prod.country,
            prod.invoice_date,
            prod.invoice_value,
            prod.shipping_agent_name,
            prod.shipping_invoice_no,
            prod.shipping_invoice_date,
            prod.shipping_invoice_value
        ])
    
    output = si.getvalue()
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=products.csv"}
    )

@app.route('/upload_products', methods=['GET', 'POST'])
def upload_products():
    """
    Renders a form to upload a CSV file and, on POST, processes the CSV
    to add new products. For each row, a new product code is generated.
    """
    if request.method == 'POST':
        file = request.files.get('file')
        if not file:
            flash("No file selected", "warning")
            return redirect(url_for('upload_products'))
        if not file.filename.endswith('.csv'):
            flash("Only CSV files are allowed", "warning")
            return redirect(url_for('upload_products'))
        
        # Read the CSV file stream (assumed to be UTF-8 encoded)
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_input = csv.DictReader(stream)
        inserted = 0
        skipped = 0
        
        for row in csv_input:
            # Generate a new product code for each row
            new_product_number = generate_new_product_number(get_last_product_number_db())
            
            # Extract fields from CSV; trim extra spaces.
            product_name = row.get("product_name", "").strip()
            rate = row.get("rate", "").strip()
            quantity = row.get("quantity", "").strip()
            
            # Require at least product_name, rate and quantity.
            if not product_name or not rate or not quantity:
                skipped += 1
                continue
            
            # For other fields, use defaults if missing.
            vat_check = row.get("vat_check", "No").strip()
            declaration_number = row.get("declaration_number", "").strip()
            release_date = row.get("release_date", "").strip()
            customs_duty = row.get("customs_duty", "0").strip()
            vat_value = row.get("vat_value", "0").strip()
            other_cost = row.get("other_cost", "0").strip()
            declared_value = row.get("declared_value", "0").strip()
            supplier_name = row.get("supplier_name", "").strip()
            supplier_invoice_no = row.get("supplier_invoice_no", "").strip()
            country = row.get("country", "").strip()
            invoice_date = row.get("invoice_date", "").strip()
            invoice_value = row.get("invoice_value", "0").strip()
            shipping_agent_name = row.get("shipping_agent_name", "").strip()
            shipping_invoice_no = row.get("shipping_invoice_no", "").strip()
            shipping_invoice_date = row.get("shipping_invoice_date", "").strip()
            shipping_invoice_value = row.get("shipping_invoice_value", "0").strip()
            
            # Build product_data list (order must match save_product_to_db expectation)
            product_data = [
                new_product_number,   # index 0: auto-generated product_s_no
                product_name,         # index 1
                rate,                 # index 2
                vat_check,            # index 3
                declaration_number,   # index 4
                release_date,         # index 5
                quantity,             # index 6
                customs_duty,         # index 7
                vat_value,            # index 8
                other_cost,           # index 9
                declared_value,       # index 10
                supplier_name,        # index 11
                supplier_invoice_no,  # index 12
                country,              # index 13
                invoice_date,         # index 14
                invoice_value,        # index 15
                shipping_agent_name,  # index 16
                shipping_invoice_no,  # index 17
                shipping_invoice_date,# index 18
                shipping_invoice_value# index 19
            ]
            
            if save_product_to_db(product_data):
                inserted += 1
            else:
                skipped += 1
        
        flash(f"CSV Upload complete. Inserted: {inserted}, Skipped: {skipped}", "success")
        return redirect(url_for('list_products'))
    
    return render_template('upload_products.html')


#*______________________________________________________________________________ Generate Invoice Functions
class Invoice:
    def __init__(self, id, invoice_number, date, customer_name, address, vat_no, po_no, items):
        self.id = id
        self.invoice_number = invoice_number
        self.date = date
        self.customer_name = customer_name
        self.address = address
        self.vat_no = vat_no
        self.po_no = po_no
        self.items = items

    @staticmethod
    def load_invoices_from_json():
        file_path = get_file_path('invoice.json')
        lock = get_file_lock('invoice.json')
        with lock:
            if not os.path.exists(file_path):
                return []
            with open(file_path, 'r', encoding='utf-8') as file:
                try:
                    invoices_data = json.load(file)
                except json.JSONDecodeError:
                    invoices_data = []

        invoice_objects = []
        for inv_data in invoices_data:
            # Remove any leftover references
            inv_data.pop('product_name', None)
            inv_data.pop('item_count', None)
            inv_data.pop('account_number', None)
            inv_data.pop('bank', None)
            inv_data.pop('branch', None)

            invoice_objects.append(Invoice(**inv_data))
        return invoice_objects

    @staticmethod
    def save_invoices_to_json(invoices):
        file_path = get_file_path('invoice.json')
        lock = get_file_lock('invoice.json')
        with lock:
            with open(file_path, 'w', encoding='utf-8') as file:
                json.dump([invoice.__dict__ for invoice in invoices], file, indent=4)

    @staticmethod
    def save_invoice_to_json(invoice_data):
        # Duplicate check by invoice_number
        invoices = Invoice.load_invoices_from_json()
        if any(i.invoice_number == invoice_data["invoice_number"] for i in invoices):
            raise ValueError("Duplicate invoice_number detected.")
        invoices.append(Invoice(**invoice_data))
        Invoice.save_invoices_to_json(invoices)

class InvoiceItem:
    def __init__(self, id, invoice_id, product_name, quantity, rate, gr_amount, vat, net_amount):
        self.id = id
        self.invoice_id = invoice_id
        self.product_name = product_name
        self.quantity = quantity
        self.rate = rate
        self.gr_amount = gr_amount
        self.vat = vat
        self.net_amount = net_amount

def get_last_invoice_number_db():
    invoices = Invoice.load_invoices_from_json()
    if not invoices:
        return None
    try:
        last_invoice = max(invoices, key=lambda i: int(i.invoice_number.split('-')[1]))
        return last_invoice.invoice_number
    except (ValueError, IndexError):
        return None

@app.route('/invoice', methods=['GET', 'POST'])
def generate_invoice():
    if request.method == 'POST':
        invoice_data = {
            "Date": request.form.get('date'),
            "Invoice Number": request.form.get('invoice_number'),
            "Customer Name": request.form.get('customer_name'),
            "Address": request.form.get('address'),
            "Customer VAT No": request.form.get('vat_no'),
            "Customer PO No": request.form.get('po_no'),
            "Products": []
        }
        try:
            product_count = int(request.form.get('product_count', 0))
        except ValueError:
            product_count = 0

        for i in range(product_count + 1):
            product_name = request.form.get(f'product_name_{i}')
            if product_name:
                try:
                    quantity = round(float(request.form.get(f'quantity_{i}') or 0), 3)
                    rate = round(float(request.form.get(f'rate_{i}') or 0), 3)
                    gr_amount = round(float(request.form.get(f'gr_amount_{i}') or 0), 3)
                    vat = round(float(request.form.get(f'vat_{i}') or 0), 3)
                    net_amount = round(float(request.form.get(f'net_amount_{i}') or 0), 3)
                except ValueError:
                    flash("Invalid numeric value in one of the product fields.", "warning")
                    return redirect(url_for('generate_invoice'))

                product_info = {
                    "Product Name": product_name,
                    "Quantity": quantity,
                    "Rate": rate,
                    "Gr Amount": gr_amount,
                    "VAT": vat,
                    "Net Amount": net_amount
                }
                invoice_data['Products'].append(product_info)

        # Basic checks
        if not all([
            invoice_data["Date"],
            invoice_data["Invoice Number"],
            invoice_data["Customer Name"],
            invoice_data["Address"],
            invoice_data["Customer VAT No"],
            invoice_data["Customer PO No"]
        ]):
            flash("Please fill out all required fields!", "warning")
            return redirect(url_for('generate_invoice'))

        if not invoice_data['Products']:
            flash("Please add at least one product to the invoice!", "warning")
            return redirect(url_for('generate_invoice'))

        if save_invoice_to_db(invoice_data):
            flash("Invoice generated successfully!", "success")
            return redirect(url_for('view_invoice', invoice_number=invoice_data["Invoice Number"]))
        else:
            flash("Error generating invoice", "danger")
            return redirect(url_for('generate_invoice'))

    # If GET, show the invoice form
    # Load customers
    customers = Customer.load_customers_from_json()
    customer_list = [{
        'name': c.customer_name,
        'address': c.address,
        'vat_no': c.vat_no,
        'po_no': c.credit_term
    } for c in customers]

    # Load products
    products = Product.load_products_from_json()
    product_list = [{'name': p.product_name, 'vat_check': p.vat_check} for p in products]

    customer_names = [cust['name'] for cust in customer_list]
    product_names = [prod['name'] for prod in product_list]

    last_invoice_number = get_last_invoice_number_db()
    new_invoice_number = generate_new_invoice_number(last_invoice_number)

    return render_template(
        'add_invoice.html', 
        customer_names=customer_names, 
        product_names=product_names, 
        new_invoice_number=new_invoice_number,
        customers=customer_list,
        products=product_list,
        datetime=datetime
    )

def save_invoice_to_db(invoice_data):
    try:
        invoices = Invoice.load_invoices_from_json()
        new_id = len(invoices) + 1
        # Minimal sanitization on top-level invoice fields
        inv_number = sanitize_string(invoice_data['Invoice Number'])
        date_str = sanitize_string(invoice_data['Date'])
        c_name = sanitize_string(invoice_data['Customer Name'])
        addr = sanitize_string(invoice_data['Address'])
        vat_no = sanitize_string(invoice_data['Customer VAT No'])
        po_no = sanitize_string(invoice_data['Customer PO No'])

        # Build product list
        sanitized_products = []
        for p in invoice_data['Products']:
            p_name = sanitize_string(p["Product Name"])
            try:
                quantity = round(float(sanitize_string(str(p["Quantity"]))), 3)
                rate = round(float(sanitize_string(str(p["Rate"]))), 3)
                gr_amount = round(float(sanitize_string(str(p["Gr Amount"]))), 3)
                vat = round(float(sanitize_string(str(p["VAT"]))), 3)
                net = round(float(sanitize_string(str(p["Net Amount"]))), 3)
            except ValueError:
                print("Skipping invalid product due to numeric parse error.")
                continue
            if p_name:
                sanitized_products.append({
                    "Product Name": p_name,
                    "Quantity": quantity,
                    "Rate": rate,
                    "Gr Amount": gr_amount,
                    "VAT": vat,
                    "Net Amount": net
                })

        invoice_data_complete = {
            'id': new_id,
            'invoice_number': inv_number,
            'date': date_str,
            'customer_name': c_name,
            'address': addr,
            'vat_no': vat_no,
            'po_no': po_no,
            # No account/bank/branch fields in stored data
            'items': [
                {
                    'id': i + 1,
                    'invoice_id': new_id,
                    'product_name': product['Product Name'],
                    'quantity': product['Quantity'],
                    'rate': product['Rate'],
                    'gr_amount': product['Gr Amount'],
                    'vat': product['VAT'],
                    'net_amount': product['Net Amount']
                } for i, product in enumerate(sanitized_products)
            ]
        }
        Invoice.save_invoice_to_json(invoice_data_complete)
        return True
    except Exception as e:
        print(f"Error saving invoice: {e}")
        return False

def generate_new_invoice_number(last_invoice_number):
    if not last_invoice_number or '-' not in last_invoice_number:
        return "T-0001"
    try:
        prefix, num = last_invoice_number.split('-')
        new_num = int(num) + 1
        new_invoice_number = f"{prefix}-{new_num:04d}"
        return new_invoice_number
    except ValueError:
        return "T-0001"

@app.template_filter('unique')
def unique_filter(value):
    # Assuming value is a list; return only unique items preserving order,
    # and skip items that are empty or None.
    seen = set()
    unique_list = []
    for item in value:
        # Skip if the item is None or an empty string.
        if item is None or item == "":
            continue
        if item not in seen:
            unique_list.append(item)
            seen.add(item)
    return unique_list


#*______________________________________________________________________________ Invoice CSV Functionality 
# @app.route('/list_invoices')
# @login_required
# def list_invoices():
#     """Render a page that displays all invoices in a table."""
#     invoices = Invoice.load_invoices_from_json()
#     return render_template('list_invoices.html', invoices=invoices)

# @app.route('/download_invoices')
# def download_invoices():
#     """Convert the invoice list into a CSV file and return it for download."""
#     invoices = Invoice.load_invoices_from_json()
#     si = io.StringIO()
#     csv_writer = csv.writer(si)
    
#     # Write header row. (We exclude the auto-generated id.)
#     csv_writer.writerow([
#         "invoice_number", "date", "customer_name", "address", "vat_no", "po_no", "items"
#     ])
    
#     for inv in invoices:
#         # Convert the items list to a JSON string.
#         items_json = json.dumps(inv.items)
#         csv_writer.writerow([
#             inv.invoice_number,
#             inv.date,
#             inv.customer_name,
#             inv.address,
#             inv.vat_no,
#             inv.po_no,
#             items_json
#         ])
    
#     output = si.getvalue()
#     return Response(
#         output,
#         mimetype="text/csv",
#         headers={"Content-disposition": "attachment; filename=invoices.csv"}
#     )

# @app.route('/upload_invoices', methods=['GET', 'POST'])
# def upload_invoices():
#     """
#     Provides a form to upload a CSV file. On POST, the CSV is read row by row.
#     For each row, a new invoice is created with an auto‑generated invoice number.
#     The CSV file should have a header with these columns:
#        date, customer_name, address, vat_no, po_no, items
#     The items column should be a JSON string representing the list of invoice items.
#     """
#     if request.method == 'POST':
#         file = request.files.get('file')
#         if not file:
#             flash("No file selected", "warning")
#             return redirect(url_for('upload_invoices'))
#         if not file.filename.endswith('.csv'):
#             flash("Only CSV files are allowed", "warning")
#             return redirect(url_for('upload_invoices'))
        
#         stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
#         csv_input = csv.DictReader(stream)
#         inserted = 0
#         skipped = 0
        
#         for row in csv_input:
#             # Auto-generate a new invoice number.
#             new_invoice_number = generate_new_invoice_number(get_last_invoice_number_db())
            
#             # Extract required fields.
#             date_str = row.get("date", "").strip()
#             customer_name = row.get("customer_name", "").strip()
#             address = row.get("address", "").strip()
#             vat_no = row.get("vat_no", "").strip()
#             po_no = row.get("po_no", "").strip()
            
#             # Try to parse the "items" column as JSON. If invalid, use an empty list.
#             items_str = row.get("items", "").strip()
#             try:
#                 products = json.loads(items_str) if items_str else []
#             except Exception as e:
#                 print(f"Error parsing items JSON: {e}")
#                 products = []
            
#             # Check that required fields are present.
#             if not date_str or not customer_name or not address or not vat_no or not po_no:
#                 skipped += 1
#                 continue
            
#             # Build the invoice_data dictionary in the format expected by your save_invoice_to_db function.
#             invoice_data = {
#                 "Date": date_str,
#                 "Invoice Number": new_invoice_number,  # Overwrite any CSV value.
#                 "Customer Name": customer_name,
#                 "Address": address,
#                 "Customer VAT No": vat_no,
#                 "Customer PO No": po_no,
#                 "Products": products   # Use key "Products" as in your existing function.
#             }
            
#             if save_invoice_to_db(invoice_data):
#                 inserted += 1
#             else:
#                 skipped += 1
        
#         flash(f"CSV Upload complete. Inserted: {inserted}, Skipped: {skipped}", "success")
#         return redirect(url_for('list_invoices'))
    
#     # GET: render the upload form.
#     return render_template('upload_invoices.html')


#*______________________________________________________________________________ Expanded Invoice Detail CSV Functionality 
@app.route('/list_invoice_details')
def list_invoice_details():
    """
    Build a normalized list of invoice details (one row per invoice item)
    and render it in a table.
    """
    invoices = Invoice.load_invoices_from_json()
    details = []
    for inv in invoices:
        # For invoices without any items, you might want to include a row indicating no items.
        if not inv.items:
            details.append({
                "invoice_number": inv.invoice_number,
                "date": inv.date,
                "customer_name": inv.customer_name,
                "address": inv.address,
                "vat_no": inv.vat_no,
                "po_no": inv.po_no,
                "product_name": "",
                "quantity": "",
                "rate": "",
                "gr_amount": "",
                "vat": "",
                "net_amount": "",

            })
        else:
            for item in inv.items:
                details.append({
                    "invoice_number": inv.invoice_number,
                    "date": inv.date,
                    "customer_name": inv.customer_name,
                    "address": inv.address,
                    "vat_no": inv.vat_no,
                    "po_no": inv.po_no,
                    "product_name": item.get("product_name", ""),
                    "quantity": item.get("quantity", ""),
                    "rate": item.get("rate", ""),
                    "gr_amount": item.get("gr_amount", ""),
                    "vat": item.get("vat", ""),
                    "net_amount": item.get("net_amount", ""),

                })
    return render_template("list_invoice_details.html", details=details)

@app.route('/download_invoice_details')
def download_invoice_details():
    """
    Build a CSV file where each row corresponds to a single invoice item,
    with the invoice header fields repeated on each row.
    """
    invoices = Invoice.load_invoices_from_json()
    si = io.StringIO()
    csv_writer = csv.writer(si)
    
    # Write header row.
    csv_writer.writerow([
        "invoice_number", "date", "customer_name", "address", "vat_no", "po_no",
        "product_name", "quantity", "rate", "gr_amount", "vat", "net_amount"
    ])
    
    for inv in invoices:
        # If an invoice has no items, output a row with empty product fields.
        if not inv.items:
            csv_writer.writerow([
                inv.invoice_number,
                inv.date,
                inv.customer_name,
                inv.address,
                inv.vat_no,
                inv.po_no,
                "",
                "",
                "",
                "",
                "",
                ""
            ])
        else:
            for item in inv.items:
                csv_writer.writerow([
                    inv.invoice_number,
                    inv.date,
                    inv.customer_name,
                    inv.address,
                    inv.vat_no,
                    inv.po_no,
                    item.get("product_name", ""),
                    item.get("quantity", ""),
                    item.get("rate", ""),
                    item.get("gr_amount", ""),
                    item.get("vat", ""),
                    item.get("net_amount", "")
                ])
    
    output = si.getvalue()
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=invoice_details.csv"}
    )


#*______________________________________________________________________________  PDF Functions
def render_pdf(template_src, context_dict={}):
    """
    Renders a PDF from the given template and context.
    Any bank/account info can be hardcoded in the template.
    """
    template = render_template(template_src, **context_dict)
    result = BytesIO()
    # Convert HTML to PDF
    pisa_status = pisa.CreatePDF(BytesIO(template.encode('utf-8')), dest=result)
    if pisa_status.err:
        return None
    return result.getvalue()


#*______________________________________________________________________________ View Invoice Functions
@app.route('/view_invoice/<invoice_number>')
def view_invoice(invoice_number):
    invoice_file = get_file_path('invoice.json')
    if os.path.exists(invoice_file):
        with open(invoice_file, 'r', encoding='utf-8') as f:
            invoices = json.load(f)
            # Find the invoice with the matching invoice_number
            invoice = next((inv for inv in invoices if inv['invoice_number'] == invoice_number), None)
            if invoice:
                # Calculate totals from the items with float conversion and 3 decimal precision
                items = invoice.get('items', [])
                total_quantity = round(sum(float(item.get('quantity', 0)) for item in items), 3)
                total_gross_amount = round(sum(float(item.get('gr_amount', 0)) for item in items), 3)
                total_vat = round(sum(float(item.get('vat', 0)) for item in items), 3)
                total_net_amount = round(sum(float(item.get('net_amount', 0)) for item in items), 3)
                
                # Add totals to the invoice dictionary
                invoice['total_quantity'] = total_quantity
                invoice['total_gross_amount'] = total_gross_amount
                invoice['total_vat'] = total_vat
                invoice['total_net_amount'] = total_net_amount

                return render_template('view_invoice.html', invoice=invoice)

    flash("Invoice not found", "danger")
    return redirect(url_for('index'))


#*______________________________________________________________________________ Edit Invoice Functions
@app.route('/edit_invoice', methods=['GET', 'POST'])
def edit_invoice():
    invoice = None
    customers = Customer.load_customers_from_json()  # Load customer data
    products = Product.load_products_from_json()    # Load product data

    # Convert Customer objects to dictionaries
    customer_list = [customer.__dict__ for customer in customers]

    # Convert Product objects to dictionaries for JSON serialization
    products = [p.__dict__ for p in products]

    if request.method == 'POST' and 'load_invoice' in request.form:
        invoice_number = request.form.get('invoice_number')
        invoice = fetch_invoice_from_db(invoice_number)

        if not invoice:
            flash("Invoice not found!", "error")

    return render_template('edit_invoice.html', invoice=invoice, customers=customer_list, products=products)

class EditInvoice:
    """
    Handles loading, fetching, editing, updating, and saving invoices in invoice.json.
    """

    DATA_DIR = os.path.join(os.getcwd(), 'database')
    INVOICE_FILE = os.path.join(DATA_DIR, 'invoice.json')
    LOCK = threading.Lock()

    @staticmethod
    def load_invoices():
        """ Load all invoices from invoice.json """
        with EditInvoice.LOCK:
            if not os.path.exists(EditInvoice.INVOICE_FILE):
                return []

            with open(EditInvoice.INVOICE_FILE, 'r', encoding='utf-8') as file:
                try:
                    return json.load(file)
                except json.JSONDecodeError:
                    return []

    @staticmethod
    def save_invoices(invoices):
        """ Save updated invoices back to invoice.json """
        with EditInvoice.LOCK:
            with open(EditInvoice.INVOICE_FILE, 'w', encoding='utf-8') as file:
                json.dump(invoices, file, indent=4)

    @staticmethod
    def get_invoice(invoice_number):
        """ Fetch a specific invoice by its invoice number. """
        invoices = EditInvoice.load_invoices()
        for invoice in invoices:
            if invoice["invoice_number"] == invoice_number:
                return invoice
        return None

    @staticmethod
    def update_invoice(invoice_number, updated_data):
        """Update an existing invoice in invoice.json."""
        invoices = EditInvoice.load_invoices()
        for i, invoice in enumerate(invoices):
            if invoice["invoice_number"] == invoice_number:
                invoices[i] = updated_data  # Replace with new details
                EditInvoice.save_invoices(invoices)
                return True
        return False
    
    @staticmethod
    def replace_invoice(invoice_number, new_invoice_data):
        """
        Completely replace an existing invoice with new data.
        - If the invoice does not exist, returns False.
        """
        invoices = EditInvoice.load_invoices()
        for i, invoice in enumerate(invoices):
            if invoice["invoice_number"] == invoice_number:
                invoices[i] = new_invoice_data  # Full replacement
                EditInvoice.save_invoices(invoices)
                return True
        return False

    @staticmethod
    def delete_invoice(invoice_number):
        """
        Delete an invoice by its invoice number.
        """
        invoices = EditInvoice.load_invoices()
        updated_invoices = [invoice for invoice in invoices if invoice["invoice_number"] != invoice_number]
        
        if len(updated_invoices) == len(invoices):
            return False  # Invoice not found

        EditInvoice.save_invoices(updated_invoices)
        return True

    @staticmethod
    def add_new_invoice(invoice_data):
        """
        Add a new invoice, ensuring no duplicate invoice_number exists.
        """
        invoices = EditInvoice.load_invoices()
        if any(invoice["invoice_number"] == invoice_data["invoice_number"] for invoice in invoices):
            return False  # Duplicate invoice

        invoices.append(invoice_data)
        EditInvoice.save_invoices(invoices)
        return True

def fetch_invoice_from_db(invoice_number):
    invoices = Invoice.load_invoices_from_json()
    invoice = next((inv for inv in invoices if inv.invoice_number == invoice_number), None)

    if not invoice:
        return None

    # Format items properly
    items = [
        {
            'product_name': item['product_name'],
            'quantity': item['quantity'],
            'rate': item['rate'],
            'gr_amount': item['gr_amount'],
            'vat': item['vat'],
            'net_amount': item['net_amount']
        }
        for item in invoice.items
    ]

    # Return formatted invoice
    return {
        'invoice_number': invoice.invoice_number,
        'date': invoice.date,
        'customer_name': invoice.customer_name,
        'address': invoice.address,
        'vat_no': invoice.vat_no,
        'po_no': invoice.po_no,
        'items': items
    }

@app.route('/update_invoice', methods=['POST'])
def update_invoice():
    invoice_number = request.form.get('invoice_number')
    # Fetch the existing invoice so we can retain fields like "id" that shouldn't be changed
    existing_invoice = EditInvoice.get_invoice(invoice_number)
    if not existing_invoice:
        flash("Invoice not found!", "error")
        return redirect(url_for('edit_invoice'))

    updated_invoice = {
        "id": existing_invoice["id"],  # Keep the original ID
        "invoice_number": invoice_number,
        "date": request.form.get('date'),
        "customer_name": request.form.get('customer_name'),
        "address": request.form.get('address'),
        "vat_no": request.form.get('vat_no'),
        "po_no": request.form.get('po_no'),
        "items": []
    }

    # Dynamically capture product details, converting numbers to float with 3 decimals precision.
    index = 1
    while request.form.get(f'product_name_{index}'):
        product_name = request.form.get(f'product_name_{index}')
        quantity = round(float(request.form.get(f'quantity_{index}', 0.0)), 3)
        rate = round(float(request.form.get(f'rate_{index}', 0.0)), 3)
        gr_amount = round(float(request.form.get(f'gr_amount_{index}', 0.0)), 3)
        vat = round(float(request.form.get(f'vat_{index}', 0.0)), 3)
        net_amount = round(float(request.form.get(f'net_amount_{index}', 0.0)), 3)

        updated_invoice["items"].append({
            "id": index,
            "product_name": product_name,
            "quantity": quantity,
            "rate": rate,
            "gr_amount": gr_amount,
            "vat": vat,
            "net_amount": net_amount
        })

        index += 1

    # Save the updated invoice to invoice.json and then redirect to view_invoice
    if EditInvoice.update_invoice(invoice_number, updated_invoice):
        flash("Invoice updated successfully!", "success")
        return redirect(url_for('view_invoice', invoice_number=invoice_number))
    else:
        flash("Invoice not found!", "error")
        return redirect(url_for('edit_invoice'))


#*______________________________________________________________________________ Record Received Functions
@app.route('/record_received', methods=['GET', 'POST'])
def record_received():
    # Load all invoices.
    all_invoices = Invoice.load_invoices_from_json()
    
    # Build a list of open invoices (those with remaining > 0)
    open_invoices = []
    for inv in all_invoices:
        # Compute invoice total as the sum of the net amounts of its items.
        invoice_total = round(sum(float(item.get('net_amount', 0)) for item in inv.items), 3)
        # Compute the total payments already applied for this invoice.
        received = round(get_total_received_for_invoice(inv.invoice_number), 3)
        remaining = round(invoice_total - received, 3)
        if remaining > 0:
            open_invoices.append({
                "invoice_number": inv.invoice_number,
                "customer_name": inv.customer_name,
                "remaining": remaining
            })
    
    if request.method == 'POST':
        # Read the top-level payment fields.
        bank_name = request.form.get('bank_name')
        recieved_amount = request.form.get('recieved_amount')
        received_date = request.form.get('received_date')
        transaction_type = request.form.get('transaction_type')
        cheque_details = request.form.get('cheque_details') if transaction_type == "Cheque" else ""
        
        # Get the lists for allocations.
        invoice_numbers = request.form.getlist('invoice_number')
        allocated_amounts = request.form.getlist('amount_againts_invoice')
        comments_list = request.form.getlist('comments')
        
        # Build the allocations array.
        allocations = []
        for inv_num, alloc, comm in zip(invoice_numbers, allocated_amounts, comments_list):
            try:
                amt = round(float(alloc), 3)
            except:
                amt = 0.0
            allocations.append({
                "invoice_number": inv_num,
                "custoemr_name": "",      # To be filled below via lookup
                "remaining_amount": 0,    # To be filled below via lookup
                "amount_againts_invoice": amt,
                "comments": comm
            })
        
        # Use helper function to fill in customer name and remaining amount for each allocation.
        for alloc in allocations:
            cust_name, rem = lookup_invoice_details(alloc["invoice_number"])
            alloc["custoemr_name"] = cust_name
            alloc["remaining_amount"] = round(rem, 3)
        
        # Build the payment record.
        try:
            payment_record = {
                "bank_name": bank_name,
                "recieved_amount": round(float(recieved_amount), 3),
                "received_date": received_date,
                "transaction_type": transaction_type,
                "cheque_details": cheque_details,
                "allocations": allocations
            }
        except ValueError:
            flash("Invalid numeric value entered.", "danger")
            return redirect(url_for('record_received'))
        
        # Append the new payment record to the payment file (e.g., received.json).
        payments_file = get_file_path('received.json')
        if os.path.exists(payments_file):
            with open(payments_file, 'r', encoding='utf-8') as f:
                try:
                    payments_data = json.load(f)
                except:
                    payments_data = []
        else:
            payments_data = []
        payments_data.append(payment_record)
        with open(payments_file, 'w', encoding='utf-8') as f:
            json.dump(payments_data, f, indent=4)
        
        flash("Payment recorded successfully.", "success")
        return redirect(url_for('index'))
    
    # For GET requests, pass the open_invoices list to the template.
    return render_template('add_received.html', open_invoices=open_invoices)

def get_total_received_for_invoice(invoice_number):
    payments_file = get_file_path('received.json')
    if not os.path.exists(payments_file):
        return 0.0
    with open(payments_file, 'r', encoding='utf-8') as f:
        try:
            payments = json.load(f)
        except json.JSONDecodeError:
            payments = []
    total = 0.0
    for payment in payments:
        for alloc in payment.get("allocations", []):
            if alloc.get("invoice_number") == invoice_number:
                try:
                    total += round(float(alloc.get("amount_againts_invoice", 0)), 3)
                except ValueError:
                    pass
    return round(total, 3)

def lookup_invoice_details(invoice_number):
    for inv in Invoice.load_invoices_from_json():
        if inv.invoice_number == invoice_number:
            invoice_total = round(sum(float(item.get('net_amount', 0)) for item in inv.items), 3)
            previous_payments = get_total_received_for_invoice(invoice_number)
            remaining = round(invoice_total - previous_payments, 3)
            return inv.customer_name, remaining
    return "", 0.0

def compute_remaining_for_invoice(invoice):
    # Compute invoice_total as the sum of the net_amount of all items with 3-decimal precision
    invoice_total = round(sum(float(item.get('net_amount', 0)) for item in invoice.items), 3)
    received = round(get_total_received_for_invoice(invoice.invoice_number), 3)
    return round(invoice_total - received, 3)


#*______________________________________________________________________________ List Received Payments
@app.route('/list_received')
def list_received():
    payments_file = get_file_path('received.json')
    if os.path.exists(payments_file):
        with open(payments_file, 'r', encoding='utf-8') as f:
            try:
                payments_data = json.load(f)
            except json.JSONDecodeError:
                payments_data = []
    else:
        payments_data = []
    return render_template('list_received.html', payments=payments_data)

@app.route('/upload_received', methods=['GET', 'POST'])
def upload_received():
    if request.method == 'POST':
        file = request.files.get('file')
        if not file:
            flash("No file selected", "warning")
            return redirect(url_for('upload_received'))
        if not file.filename.endswith('.csv'):
            flash("Only CSV files are allowed", "warning")
            return redirect(url_for('upload_received'))

        # Read the CSV file.
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_input = csv.DictReader(stream)

        # We assume the detailed CSV has the following headers:
        # bank_name, recieved_amount, received_date, transaction_type, cheque_details,
        # invoice_number, custoemr_name, remaining_amount, amount_againts_invoice, comments

        # Use a dict to group rows by top-level payment details.
        payments_dict = {}

        for row in csv_input:
            # Read top-level fields.
            bank_name = row.get("bank_name", "").strip()
            recieved_amount = row.get("recieved_amount", "").strip()
            received_date = row.get("received_date", "").strip()
            transaction_type = row.get("transaction_type", "").strip()
            cheque_details = row.get("cheque_details", "").strip()

            # Create a key based on these top-level fields.
            payment_key = (bank_name, recieved_amount, received_date, transaction_type, cheque_details)

            # Initialize the grouping if it doesn't exist.
            if payment_key not in payments_dict:
                payments_dict[payment_key] = {
                    "bank_name": bank_name,
                    "recieved_amount": None,  # We'll convert to float below.
                    "received_date": received_date,
                    "transaction_type": transaction_type,
                    "cheque_details": cheque_details,
                    "allocations": []
                }
                try:
                    payments_dict[payment_key]["recieved_amount"] = round(float(recieved_amount), 3)
                except ValueError:
                    payments_dict[payment_key]["recieved_amount"] = 0.0

            # Process allocation columns.
            invoice_number = row.get("invoice_number", "").strip()
            # If invoice_number is blank, assume there is no allocation for this row.
            if invoice_number:
                # Create an allocation record.
                try:
                    alloc_amount = round(float(row.get("amount_againts_invoice", "0").strip()), 3)
                except ValueError:
                    alloc_amount = 0.0

                try:
                    remaining_amt = round(float(row.get("remaining_amount", "0").strip() or 0), 3)
                except ValueError:
                    remaining_amt = 0.0

                allocation = {
                    "invoice_number": invoice_number,
                    "custoemr_name": row.get("custoemr_name", "").strip(),
                    "remaining_amount": remaining_amt,
                    "amount_againts_invoice": alloc_amount,
                    "comments": row.get("comments", "").strip()
                }
                payments_dict[payment_key]["allocations"].append(allocation)
            # If no allocation details are provided, then leave allocations as empty.
        
        # Convert the grouped payments into a list.
        new_payments = list(payments_dict.values())
        inserted = len(new_payments)

        # Optionally, you can run each allocation through a lookup to ensure
        # that the customer name and remaining amount are correctly set.
        for payment in new_payments:
            for alloc in payment["allocations"]:
                cust_name, rem = lookup_invoice_details(alloc["invoice_number"])
                # Only update if missing or if you want to refresh the values.
                if not alloc.get("custoemr_name"):
                    alloc["custoemr_name"] = cust_name
                if not alloc.get("remaining_amount"):
                    alloc["remaining_amount"] = round(rem, 3)

        # Load existing payments from received.json.
        payments_file = get_file_path('received.json')
        if os.path.exists(payments_file):
            with open(payments_file, 'r', encoding='utf-8') as f:
                try:
                    existing_payments = json.load(f)
                except json.JSONDecodeError:
                    existing_payments = []
        else:
            existing_payments = []

        # Append the new payments and write back.
        existing_payments.extend(new_payments)
        with open(payments_file, 'w', encoding='utf-8') as f:
            json.dump(existing_payments, f, indent=4)

        flash(f"CSV Upload complete. Inserted: {inserted}", "success")
        return redirect(url_for('list_received'))

    return render_template('upload_received.html')

@app.route('/download_received_detailed')
def download_received_detailed():
    payments_file = get_file_path('received.json')
    if os.path.exists(payments_file):
        with open(payments_file, 'r', encoding='utf-8') as f:
            try:
                payments_data = json.load(f)
            except json.JSONDecodeError:
                payments_data = []
    else:
        payments_data = []

    def format_float(value):
        try:
            return f"{float(value):.3f}"
        except (ValueError, TypeError):
            return value

    si = io.StringIO()
    csv_writer = csv.writer(si)

    # Write header row.
    csv_writer.writerow([
        "bank_name", "recieved_amount", "received_date",
        "transaction_type", "cheque_details",
        "invoice_number", "custoemr_name", "remaining_amount",
        "amount_againts_invoice", "comments"
    ])

    # Write one row per allocation.
    for payment in payments_data:
        bank_name = payment.get("bank_name", "")
        recieved_amount = format_float(payment.get("recieved_amount", ""))
        received_date = payment.get("received_date", "")
        transaction_type = payment.get("transaction_type", "")
        cheque_details = payment.get("cheque_details", "")
        allocations = payment.get("allocations", [])
        if allocations:
            for alloc in allocations:
                invoice_number = alloc.get("invoice_number", "")
                custoemr_name = alloc.get("custoemr_name", "")
                remaining_amount = format_float(alloc.get("remaining_amount", ""))
                amount_againts_invoice = format_float(alloc.get("amount_againts_invoice", ""))
                comments = alloc.get("comments", "")
                csv_writer.writerow([
                    bank_name, recieved_amount, received_date,
                    transaction_type, cheque_details,
                    invoice_number, custoemr_name, remaining_amount,
                    amount_againts_invoice, comments
                ])
        else:
            # If there are no allocations, output one row with empty allocation columns.
            csv_writer.writerow([
                bank_name, recieved_amount, received_date,
                transaction_type, cheque_details,
                "", "", "", "", ""
            ])

    output = si.getvalue()
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=received_payments_detailed.csv"}
    )

def lookup_invoice_details(invoice_number):
    # Loop through invoices from your invoice database.
    for inv in Invoice.load_invoices_from_json():
        if inv.invoice_number == invoice_number:
            # Compute invoice total (sum of net_amount of items) rounded to 3 decimals.
            invoice_total = round(sum(float(item.get('net_amount', 0)) for item in inv.items), 3)
            # Get previous payments applied (using your helper) and round to 3 decimals.
            previous_payments = round(get_total_received_for_invoice(invoice_number), 3)
            # Calculate remaining amount rounded to 3 decimals.
            remaining = round(invoice_total - previous_payments, 3)
            return inv.customer_name, remaining
    return "", 0.0

#*______________________________________________________________________________ List Receivable
@app.route('/list_receivable')
def list_receivable():
    """
    Render a page that displays all invoices with remaining receivables.
    The remaining amount is calculated by subtracting the total received
    from the invoice total (sum of the net amounts of its items), all rounded to 3 decimals.
    """
    invoices = Invoice.load_invoices_from_json()  # Load all invoices
    receivables = []
    total_invoice_sum = 0.0
    total_received_sum = 0.0
    total_remaining_sum = 0.0

    # Loop through each invoice and calculate the remaining receivable
    for invoice in invoices:
        invoice_total = round(sum(float(item.get('net_amount', 0)) for item in invoice.items), 3)
        received = round(get_total_received_for_invoice(invoice.invoice_number), 3)
        remaining_receivable = round(invoice_total - received, 3)

        if remaining_receivable > 0:  # Only show invoices with remaining balance
            receivables.append({
                "invoice_number": invoice.invoice_number,
                "customer_name": invoice.customer_name,
                "invoice_total": f"{invoice_total:.3f}",
                "total_received": f"{received:.3f}",
                "remaining_receivable": f"{remaining_receivable:.3f}",
                "invoice_date": invoice.date  # Add the invoice date
            })

            # Update the totals
            total_invoice_sum += invoice_total
            total_received_sum += received
            total_remaining_sum += remaining_receivable

    return render_template(
        'list_receivable.html',
        receivables=receivables,
        total_invoice=f"{total_invoice_sum:.3f}",
        total_received=f"{total_received_sum:.3f}",
        total_remaining=f"{total_remaining_sum:.3f}"
    )

@app.route('/download_receivable')
def download_receivable():
    # Load all invoices
    invoices = Invoice.load_invoices_from_json()
    receivables = []
    total_invoice = 0.0
    total_received_total = 0.0
    total_remaining = 0.0

    # Calculate receivables for each invoice
    for invoice in invoices:
        # Calculate invoice total (sum of net_amounts) and round to 3 decimal places
        invoice_total = round(sum(float(item.get('net_amount', 0)) for item in invoice.items), 3)
        # Get the total amount received for this invoice and round it
        received = round(get_total_received_for_invoice(invoice.invoice_number), 3)
        # Calculate remaining receivable and round it
        remaining_receivable = round(invoice_total - received, 3)

        if remaining_receivable > 0:
            receivables.append({
                "invoice_number": invoice.invoice_number,
                "customer_name": invoice.customer_name,
                "invoice_date": invoice.date,
                "invoice_total": invoice_total,
                "total_received": received,
                "remaining_receivable": remaining_receivable
            })
            total_invoice += invoice_total
            total_received_total += received
            total_remaining += remaining_receivable

    # Generate CSV data
    si = io.StringIO()
    writer = csv.writer(si)

    # Write header
    writer.writerow([
        "Invoice Number",
        "Customer Name",
        "Date of Invoice",
        "Invoice Total",
        "Total Received",
        "Remaining Receivable"
    ])

    # Write receivables rows with float values formatted to 3 decimal places
    for rec in receivables:
        writer.writerow([
            rec["invoice_number"],
            rec["customer_name"],
            rec["invoice_date"],
            f"{rec['invoice_total']:.3f}",
            f"{rec['total_received']:.3f}",
            f"{rec['remaining_receivable']:.3f}"
        ])

    # Write totals row with values formatted to 3 decimals
    writer.writerow([
        "Total", "", "",
        f"{total_invoice:.3f}",
        f"{total_received_total:.3f}",
        f"{total_remaining:.3f}"
    ])

    output = si.getvalue()
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=receivables.csv"}
    )

def get_total_received_for_invoice(invoice_number):
    payments_file = get_file_path('received.json')
    if not os.path.exists(payments_file):
        return 0.0
    with open(payments_file, 'r', encoding='utf-8') as f:
        try:
            payments = json.load(f)
        except json.JSONDecodeError:
            payments = []
    total = 0.0
    for payment in payments:
        for alloc in payment.get("allocations", []):
            if alloc.get("invoice_number") == invoice_number:
                try:
                    total += float(alloc.get("amount_againts_invoice", 0))
                except ValueError:
                    pass
    return round(total, 3)


#*______________________________________________________________________________ success Routes
@app.route('/success')
def success():
    # If you pass ?inv_no=some_number in the URL,
    # you can show a link to the PDF in success.html
    invoice_number = request.args.get('inv_no')
    return render_template('success.html', invoice_number=invoice_number)






#&______________________________________________________________________________ admin Routes
#&______________________________________________________________________________ admin Routes
#&______________________________________________________________________________ admin Routes

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.admin:
            abort(403)  # Forbidden
        return f(*args, **kwargs)
    return decorated_function


@app.route('/delete_supplier/<supplier_s_no>', methods=['POST'])
@login_required
@admin_required
def delete_supplier(supplier_s_no):
    suppliers = Supplier.load_suppliers_from_json()
    new_suppliers = [s for s in suppliers if s.supplier_s_no != supplier_s_no]
    if len(new_suppliers) == len(suppliers):
        flash("Supplier not found.", "warning")
    else:
        Supplier.save_suppliers_to_json(new_suppliers)
        flash("Supplier deleted successfully.", "success")
    return redirect(url_for('list_suppliers'))

@app.route('/delete_customer/<customer_s_no>', methods=['POST'])
@login_required
@admin_required
def delete_customer(customer_s_no):
    customers = Customer.load_customers_from_json()
    new_customers = [c for c in customers if c.customer_s_no != customer_s_no]
    if len(new_customers) == len(customers):
        flash("Customer not found.", "warning")
    else:
        Customer.save_customers_to_json(new_customers)
        flash("Customer deleted successfully.", "success")
    return redirect(url_for('list_customers'))

# Delete a product by its product_s_no.
@app.route('/delete_product/<product_s_no>', methods=['POST'])
@login_required
@admin_required
def delete_product(product_s_no):
    products = Product.load_products_from_json()
    new_products = [p for p in products if p.product_s_no != product_s_no]
    if len(new_products) == len(products):
        flash("Product not found.", "warning")
    else:
        Product.save_products_to_json(new_products)
        flash("Product deleted successfully.", "success")
    return redirect(url_for('list_products'))

@app.route('/delete_invoice_detail/<invoice_number>/<int:item_id>', methods=['POST'])
@login_required
@admin_required
def delete_invoice_detail(invoice_number, item_id):
    """
    Deletes a single invoice item (identified by its 'id') from the invoice
    specified by 'invoice_number'. This does not delete the entire invoice.
    """
    invoices = Invoice.load_invoices_from_json()
    invoice_found = False
    item_found = False

    # Loop through invoices to find the matching invoice by invoice_number.
    for inv in invoices:
        if inv.invoice_number == invoice_number:
            invoice_found = True
            # Loop through the items of the found invoice.
            for idx, item in enumerate(inv.items):
                # Compare the unique item id.
                if int(item.get("id", 0)) == item_id:
                    del inv.items[idx]
                    item_found = True
                    break
            break

    if invoice_found and item_found:
        Invoice.save_invoices_to_json(invoices)
        flash("Invoice product deleted successfully.", "success")
    else:
        flash("Invoice product not found.", "warning")
    return redirect(url_for('list_invoice_details'))

# Delete an entire invoice.
@app.route('/delete_invoice/<invoice_number>', methods=['POST'])
@login_required
@admin_required
def delete_invoice(invoice_number):
    """
    Deletes the entire invoice (and all of its items) identified by invoice_number.
    """
    invoices = Invoice.load_invoices_from_json()
    new_invoices = [inv for inv in invoices if inv.invoice_number != invoice_number]
    if len(new_invoices) == len(invoices):
        flash("Invoice not found.", "warning")
    else:
        Invoice.save_invoices_to_json(new_invoices)
        flash("Invoice deleted successfully.", "success")
    return redirect(url_for('list_invoice_details'))



@app.route('/delete_received/<int:payment_index>', methods=['POST'])
@login_required
@admin_required
def delete_received(payment_index):
    payments_file = get_file_path('received.json')
    if not os.path.exists(payments_file):
        flash("No payment records found.", "warning")
        return redirect(url_for('list_received'))
    
    with open(payments_file, 'r', encoding='utf-8') as f:
        try:
            payments_data = json.load(f)
        except json.JSONDecodeError:
            payments_data = []

    if 0 <= payment_index < len(payments_data):
        payments_data.pop(payment_index)
        with open(payments_file, 'w', encoding='utf-8') as f:
            json.dump(payments_data, f, indent=4)
        flash("Payment record deleted successfully.", "success")
    else:
        flash("Payment record not found.", "warning")
    
    return redirect(url_for('list_received'))


#&______________________________________________________________________________ admin Routes
#&______________________________________________________________________________ admin Routes
#&______________________________________________________________________________ admin Routes
























#*______________________________________________________________________________ RUN THE APPLICATION
if __name__ == '__main__':
    # NOTE: debug=True is for development only
    app.run(debug=True)
