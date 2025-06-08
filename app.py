from flask import Flask, render_template, request, redirect, url_for, flash, session
from datetime import timedelta, datetime
import mysql.connector
from mysql.connector import Error

app = Flask(__name__)

# --- THESE ARE CRUCIAL FOR SESSIONS ---
app.config['SECRET_KEY'] = 'a_very_long_and_random_secret_key_that_you_should_change_for_production' # IMPORTANT: Change this for production!
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=60) # Session lasts for 60 minutes of inactivity
app.config['SESSION_REFRESH_EACH_REQUEST'] = True # Extends session on each request
# --- END SESSION CONFIG ---


# Database connection function
def get_db_connection():
    """Establishes and returns a database connection."""
    return mysql.connector.connect(
        host='localhost',
        user='root',
        password='', # Consider fetching from environment variables for security
        database='bloodbank_db'
    )

# Helper function to get all blood groups (ID and Name) for dropdowns
def get_all_blood_groups():
    conn = None
    cursor = None
    blood_groups = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, group_name FROM blood_groups ORDER BY group_name ASC")
        blood_groups = cursor.fetchall()
    except Error as e:
        print(f"Error fetching blood groups: {e}") # Print to console, not flash
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return blood_groups

# Helper function to get blood_group_id from group_name (useful if you only have the name in some legacy part)
def get_blood_group_id(group_name):
    conn = None
    cursor = None
    blood_group_id = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM blood_groups WHERE group_name = %s", (group_name,))
        result = cursor.fetchone()
        if result:
            blood_group_id = result[0]
    except Error as e:
        print(f"Error getting blood group ID for {group_name}: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return blood_group_id

# Context Processor to inject current_year into all templates
@app.context_processor
def inject_current_year():
    """Injects the current year into the template context."""
    return {'current_year': datetime.now().year}

# --- ROUTES ---

@app.route('/')
def home():
    """Redirects the root URL to the public blood availability page for non-admin users."""
    return redirect(url_for('check_availability'))

# Admin Login Route
@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    """Handles admin login, sets session, and redirects to dashboard on success."""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if username == 'admin' and password == 'adminpass':
            session['admin_user'] = username
            session.permanent = True
            flash('Logged in successfully!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid username or password', 'danger')
            return render_template('admin_login.html')
    return render_template('admin_login.html')

# Admin Dashboard Route
@app.route('/admin_dashboard')
def admin_dashboard():
    """Displays the admin dashboard, protected by session check, with key statistics."""
    if 'admin_user' not in session:
        return redirect(url_for('admin_login'))
    
    conn = None
    cursor = None
    
    total_donors = 0
    total_patients = 0
    pending_requests = 0
    total_blood_units = 0

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM donors")
        total_donors = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM patients")
        total_patients = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM blood_requests WHERE status = 'Pending'")
        pending_requests = cursor.fetchone()[0]

        cursor.execute("SELECT SUM(units_available) FROM inventory")
        total_blood_units = cursor.fetchone()[0] or 0 

    except Error as e:
        flash(f"Database error loading dashboard statistics: {e}", "danger")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return render_template('admin_dashboard.html', 
                           admin_user=session['admin_user'],
                           total_donors=total_donors,
                           total_patients=total_patients,
                           pending_requests=pending_requests,
                           total_blood_units=total_blood_units)

# Admin Logout Route
@app.route('/admin_logout')
def admin_logout():
    """Logs out the admin by removing their session data."""
    session.pop('admin_user', None)
    flash("Logged out successfully.", "info")
    return redirect(url_for('admin_login'))

# Patient List Route
@app.route('/patients')
def patients():
    """Displays a list of all patients, protected by admin session. Includes search functionality."""
    if 'admin_user' not in session:
        return redirect(url_for('admin_login'))
    
    conn = None
    cursor = None
    patients_data = []
    search_query = request.args.get('search_query', '').strip()

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Select patient_id explicitly along with other columns
        sql_query = """
            SELECT p.patient_id, p.name, p.age, p.gender, p.phone, p.city, bg.group_name 
            FROM patients p
            JOIN blood_groups bg ON p.blood_group_id = bg.id
        """
        query_params = []
        where_clauses = []

        if search_query:
            where_clauses.append("(p.name LIKE %s OR bg.group_name LIKE %s OR p.city LIKE %s)")
            query_params.extend([f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"])
        
        if where_clauses:
            sql_query += " WHERE " + " AND ".join(where_clauses)
        
        sql_query += " ORDER BY p.name ASC"

        cursor.execute(sql_query, tuple(query_params))
        patients_data = cursor.fetchall()
        
    except Error as e:
        flash(f"Database error loading patients: {e}", "danger")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return render_template('patients.html', patients=patients_data, search_query=search_query)

# Add Patient Route
@app.route('/add_patient', methods=['GET', 'POST'])
def add_patient():
    """Handles adding a new patient, protected by admin session."""
    if 'admin_user' not in session:
        return redirect(url_for('admin_login'))
    
    blood_groups = get_all_blood_groups() # Fetch blood groups for dropdown

    if request.method == 'POST':
        name = request.form['name']
        blood_group_id = request.form['blood_group_id'] # Now get ID
        age = request.form['age']
        gender = request.form['gender']
        phone = request.form['phone']
        city = request.form['city']
        
        conn = None
        cursor = None

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO patients (name, blood_group_id, age, gender, phone, city) VALUES (%s, %s, %s, %s, %s, %s)",
                           (name, blood_group_id, age, gender, phone, city))
            conn.commit()
            flash("Patient added successfully!", "success")
            return redirect(url_for('patients'))
        except Error as e:
            flash(f"Database Error: {e}", "danger")
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
                
    return render_template('add_patient.html', blood_groups=blood_groups)

# Edit Patient Route
@app.route('/edit_patient/<int:patient_id>', methods=['GET', 'POST'])
def edit_patient(patient_id):
    """Handles editing an existing patient's details, protected by admin session."""
    if 'admin_user' not in session:
        return redirect(url_for('admin_login'))
    
    conn = None
    cursor = None
    patient = None
    blood_groups = get_all_blood_groups() # Fetch blood groups for dropdown

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        if request.method == 'POST':
            name = request.form['name']
            blood_group_id = request.form['blood_group_id'] # Get ID
            age = request.form['age']
            gender = request.form['gender']
            phone = request.form['phone']
            city = request.form['city']
            cursor.execute("UPDATE patients SET name=%s, blood_group_id=%s, age=%s, gender=%s, phone=%s, city=%s WHERE patient_id=%s",
                           (name, blood_group_id, age, gender, phone, city, patient_id))
            conn.commit()
            flash("Patient updated successfully!", "success")
            return redirect(url_for('patients'))
        
        # Select patient data and join to get group_name
        cursor.execute("""
            SELECT p.patient_id, p.name, p.age, p.gender, p.phone, p.city, p.blood_group_id, bg.group_name 
            FROM patients p
            JOIN blood_groups bg ON p.blood_group_id = bg.id
            WHERE p.patient_id = %s
        """, (patient_id,))
        patient = cursor.fetchone()
        
        if not patient:
            flash("Patient not found.", "danger")
            return redirect(url_for('patients'))

    except Error as e:
        flash(f"Database error during patient edit: {e}", "danger")
        return redirect(url_for('patients'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return render_template('edit_patient.html', patient=patient, blood_groups=blood_groups)

# Delete Patient Route
@app.route('/delete_patient/<int:patient_id>', methods=['POST'])
def delete_patient(patient_id):
    """Handles deleting a patient record, protected by admin session."""
    if 'admin_user' not in session:
        flash("Please login first.", "warning")
        return redirect(url_for('admin_login'))
    
    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM patients WHERE patient_id = %s", (patient_id,))
        conn.commit()
        flash("Patient deleted successfully.", "success")
    except Error as e:
        flash(f"Database error: {e}", "danger")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
            
    return redirect(url_for('patients'))

# --- Donor Management Routes ---

@app.route('/donors')
def donors():
    """Displays a list of all donors, protected by admin session. Includes search functionality."""
    if 'admin_user' not in session:
        return redirect(url_for('admin_login'))
    
    conn = None
    cursor = None
    donors_data = []
    search_query = request.args.get('search_query', '').strip()

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Select donor_id explicitly along with other columns
        sql_query = """
            SELECT d.donor_id, d.name, d.age, d.gender, d.phone, d.email, d.last_donated_date, d.city, bg.group_name 
            FROM donors d
            JOIN blood_groups bg ON d.blood_group_id = bg.id
        """
        query_params = []
        where_clauses = []

        if search_query:
            where_clauses.append("(d.name LIKE %s OR bg.group_name LIKE %s OR d.city LIKE %s)")
            query_params.extend([f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"])
        
        if where_clauses:
            sql_query += " WHERE " + " AND ".join(where_clauses)
        
        sql_query += " ORDER BY d.name ASC"

        cursor.execute(sql_query, tuple(query_params))
        donors_data = cursor.fetchall()
        
    except Error as e:
        flash(f"Database error loading donors: {e}", "danger")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
            
    return render_template('donors.html', donors=donors_data, search_query=search_query)

@app.route('/add_donor', methods=['GET', 'POST'])
def add_donor():
    """Handles adding a new donor, protected by admin session."""
    if 'admin_user' not in session:
        return redirect(url_for('admin_login'))
    
    blood_groups = get_all_blood_groups() # Fetch blood groups for dropdown

    if request.method == 'POST':
        name = request.form['name']
        blood_group_id = request.form['blood_group_id'] # Get ID
        age = request.form['age']
        gender = request.form['gender']
        phone = request.form['phone']
        email = request.form.get('email')
        last_donated_date = request.form.get('last_donated_date')
        city = request.form['city']

        conn = None
        cursor = None
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO donors (name, blood_group_id, age, gender, phone, email, last_donated_date, city) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                           (name, blood_group_id, age, gender, phone, email, last_donated_date, city))
            conn.commit()
            flash("Donor added successfully!", "success")
            return redirect(url_for('donors'))
        except Error as e:
            flash(f"Database Error: {e}", "danger")
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
                
    return render_template('add_donor.html', blood_groups=blood_groups)

@app.route('/edit_donor/<int:donor_id_param>', methods=['GET', 'POST'])
def edit_donor(donor_id_param):
    """Handles editing an existing donor's details, protected by admin session."""
    if 'admin_user' not in session:
        return redirect(url_for('admin_login'))
    
    conn = None
    cursor = None
    donor = None
    blood_groups = get_all_blood_groups() # Fetch blood groups for dropdown

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        if request.method == 'POST':
            name = request.form['name']
            blood_group_id = request.form['blood_group_id'] # Get ID
            age = request.form['age']
            gender = request.form['gender']
            phone = request.form['phone']
            email = request.form.get('email')
            last_donated_date = request.form.get('last_donated_date')
            city = request.form['city']
            cursor.execute("UPDATE donors SET name=%s, blood_group_id=%s, age=%s, gender=%s, phone=%s, email=%s, last_donated_date=%s, city=%s WHERE donor_id=%s",
                           (name, blood_group_id, age, gender, phone, email, last_donated_date, city, donor_id_param))
            conn.commit()
            flash("Donor updated successfully!", "success")
            return redirect(url_for('donors'))
        
        # Select donor data and join to get group_name
        cursor.execute("""
            SELECT d.donor_id, d.name, d.age, d.gender, d.phone, d.email, d.last_donated_date, d.city, d.blood_group_id, bg.group_name 
            FROM donors d
            JOIN blood_groups bg ON d.blood_group_id = bg.id
            WHERE d.donor_id = %s
        """, (donor_id_param,))
        donor = cursor.fetchone()
        
        if not donor:
            flash("Donor not found.", "danger")
            return redirect(url_for('donors'))

    except Error as e:
        flash(f"Database error during donor edit: {e}", "danger")
        return redirect(url_for('donors'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return render_template('edit_donor.html', donor=donor, blood_groups=blood_groups)

@app.route('/delete_donor/<int:donor_id_param>', methods=['POST'])
def delete_donor(donor_id_param):
    """Handles deleting a donor record, protected by admin session."""
    if 'admin_user' not in session:
        flash("Please login first.", "warning")
        return redirect(url_for('admin_login'))
    
    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM donors WHERE donor_id = %s", (donor_id_param,))
        conn.commit()
        flash("Donor deleted successfully.", "success")
    except Error as e:
        flash(f"Database error: {e}", "danger")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
            
    return redirect(url_for('donors'))

# --- Blood Requests Management Routes (Admin) ---

@app.route('/blood_requests')
def blood_requests():
    """Displays a list of all blood requests, protected by admin session. Includes search functionality."""
    if 'admin_user' not in session:
        return redirect(url_for('admin_login'))
    
    conn = None
    cursor = None
    requests_data = []
    search_query = request.args.get('search_query', '').strip()

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        sql_query = """
            SELECT br.*, bg.group_name 
            FROM blood_requests br
            JOIN blood_groups bg ON br.blood_group_id = bg.id
        """
        query_params = []
        where_clauses = []

        if search_query:
            where_clauses.append("(br.patient_name LIKE %s OR bg.group_name LIKE %s OR br.status LIKE %s OR br.requested_by LIKE %s)")
            query_params.extend([f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"])
        
        if where_clauses:
            sql_query += " WHERE " + " AND ".join(where_clauses)
        
        sql_query += " ORDER BY br.status ASC, br.request_date DESC"

        cursor.execute(sql_query, tuple(query_params))
        requests_data = cursor.fetchall()
    except Error as e:
        flash(f"Database error loading blood requests: {e}", "danger")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
            
    return render_template('blood_requests.html', requests=requests_data, search_query=search_query)

@app.route('/add_blood_request', methods=['GET'])
def add_blood_request():
    """Handles adding a new blood request (admin view), protected by admin session.
    Redirects to public form which handles both public and admin additions."""
    if 'admin_user' not in session:
        return redirect(url_for('admin_login'))
    
    # This route now reuses the public_add_blood_request logic
    return redirect(url_for('public_add_blood_request')) 

@app.route('/edit_blood_request/<int:request_id_param>', methods=['GET', 'POST'])
def edit_blood_request(request_id_param):
    """Handles editing a blood request and integrates with inventory, protected by admin session."""
    if 'admin_user' not in session:
        return redirect(url_for('admin_login'))
    
    conn = None
    cursor = None
    blood_request = None
    blood_groups = get_all_blood_groups() # Fetch blood groups for dropdown

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True) 
        
        # Fetch current request details before update to check old status and get group_name
        cursor.execute("""
            SELECT br.*, bg.group_name 
            FROM blood_requests br
            JOIN blood_groups bg ON br.blood_group_id = bg.id
            WHERE br.request_id = %s
        """, (request_id_param,))
        original_request = cursor.fetchone()

        if not original_request:
            flash("Blood request not found.", "danger")
            return redirect(url_for('blood_requests'))

        if request.method == 'POST':
            patient_name = request.form['patient_name']
            blood_group_id = request.form['blood_group_id'] # Get ID
            quantity_units = int(request.form['quantity_units'])
            request_date = request.form['request_date']
            new_status = request.form['status']
            reason = request.form.get('reason')
            requested_by = request.form.get('requested_by')
            
            # Use original_request's group_name for inventory check, or re-fetch from ID if group_id changed
            current_blood_group_name = original_request['group_name']
            
            # If blood group was changed during edit, need to re-fetch its name for inventory logic
            if str(blood_group_id) != str(original_request['blood_group_id']):
                temp_cursor = conn.cursor(dictionary=True)
                temp_cursor.execute("SELECT group_name FROM blood_groups WHERE id = %s", (blood_group_id,))
                new_group_name_result = temp_cursor.fetchone()
                if new_group_name_result:
                    current_blood_group_name = new_group_name_result['group_name']
                temp_cursor.close()


            if new_status == 'Fulfilled' and original_request['status'] != 'Fulfilled':
                cursor.execute("SELECT units_available FROM inventory WHERE blood_group_id = %s", (blood_group_id,))
                inventory_result = cursor.fetchone()

                if inventory_result and inventory_result['units_available'] >= quantity_units:
                    new_inventory_units = inventory_result['units_available'] - quantity_units
                    cursor.execute("UPDATE inventory SET units_available = %s WHERE blood_group_id = %s", (new_inventory_units, blood_group_id))
                    conn.commit()
                    flash(f"Blood request fulfilled! {quantity_units} units of {current_blood_group_name} deducted from inventory.", "success")
                else:
                    available_units = inventory_result['units_available'] if inventory_result else 0
                    flash(f"Insufficient units of {current_blood_group_name} in inventory to fulfill request ({quantity_units} requested, {available_units} available).", "danger")
                    new_status = original_request['status'] # Keep original status if not fulfilled
                    conn.rollback()
                    return redirect(url_for('blood_requests'))
            elif new_status != 'Fulfilled' and original_request['status'] == 'Fulfilled':
                 flash("Changing a fulfilled request's status will not automatically return units to inventory (feature not implemented).", "warning")

            cursor.execute("UPDATE blood_requests SET patient_name=%s, blood_group_id=%s, quantity_units=%s, request_date=%s, status=%s, reason=%s, requested_by=%s WHERE request_id=%s",
                           (patient_name, blood_group_id, quantity_units, request_date, new_status, reason, requested_by, request_id_param))
            conn.commit()
            
            # Only show success message if fulfillment logic didn't already
            if not (new_status == 'Fulfilled' and original_request['status'] != 'Fulfilled'):
                flash("Blood request updated successfully!", "success")
            return redirect(url_for('blood_requests'))
        
        blood_request = original_request # Pass the fetched original request to the template
        
    except ValueError:
        flash("Invalid quantity. Please enter a whole number for units.", "danger")
        return redirect(url_for('blood_requests'))
    except Error as e:
        flash(f"Database error during blood request edit: {e}", "danger")
        if conn:
            conn.rollback()
        return redirect(url_for('blood_requests'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return render_template('edit_blood_request.html', request=blood_request, blood_groups=blood_groups)

@app.route('/delete_blood_request/<int:request_id_param>', methods=['POST'])
def delete_blood_request(request_id_param):
    """Handles deleting a blood request, protected by admin session."""
    if 'admin_user' not in session:
        return redirect(url_for('admin_login'))
    
    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM blood_requests WHERE request_id = %s", (request_id_param,))
        conn.commit()
        flash("Blood request deleted successfully.", "success")
    except Error as e:
        flash(f"Database error: {e}", "danger")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
            
    return redirect(url_for('blood_requests'))

# --- Inventory Management Routes ---

@app.route('/inventory', methods=['GET', 'POST'])
def inventory():
    """Displays and updates blood inventory, protected by admin session."""
    if 'admin_user' not in session:
        return redirect(url_for('admin_login'))
    
    conn = None
    cursor = None
    inventory_data = []
    blood_groups = get_all_blood_groups() # Fetch blood groups for dropdown

    if request.method == 'POST':
        blood_group_id = request.form['blood_group_id'] # Now using ID
        units_change = int(request.form['units_change'])
        action = request.form['action']

        # Get the group name for flash messages
        selected_group_name = next((bg['group_name'] for bg in blood_groups if str(bg['id']) == str(blood_group_id)), "Unknown Group")

        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)

            cursor.execute("SELECT units_available FROM inventory WHERE blood_group_id = %s", (blood_group_id,))
            current_units_result = cursor.fetchone()

            if current_units_result:
                current_units = current_units_result['units_available']
                new_units = current_units # Initialize with current_units

                if action == 'add':
                    new_units = current_units + units_change
                    flash(f"Added {units_change} units to {selected_group_name}.", "success")
                elif action == 'subtract':
                    if current_units >= units_change:
                        new_units = current_units - units_change
                        flash(f"Subtracted {units_change} units from {selected_group_name}.", "info")
                    else:
                        flash(f"Cannot subtract {units_change} units. Only {current_units} available for {selected_group_name}.", "danger")
                        new_units = current_units # Keep current units if subtraction fails
                
                cursor.execute("UPDATE inventory SET units_available = %s, last_updated = CURRENT_TIMESTAMP() WHERE blood_group_id = %s", (new_units, blood_group_id))
                conn.commit()
            else:
                if action == 'add':
                    cursor.execute("INSERT INTO inventory (blood_group_id, units_available, last_updated) VALUES (%s, %s, CURRENT_TIMESTAMP())", (blood_group_id, units_change))
                    conn.commit()
                    flash(f"Added new blood group {selected_group_name} with {units_change} units.", "success")
                else:
                    flash(f"Blood group {selected_group_name} not found in inventory. Cannot subtract units.", "danger")

        except ValueError:
            flash("Invalid quantity. Please enter a whole number.", "danger")
        except Error as e:
            flash(f"Database error updating inventory: {e}", "danger")
            if conn:
                conn.rollback()
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
        
        return redirect(url_for('inventory')) 

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # Join to get group_name for display
        cursor.execute("""
            SELECT i.units_available, i.last_updated, bg.group_name, i.blood_group_id
            FROM inventory i
            JOIN blood_groups bg ON i.blood_group_id = bg.id
            ORDER BY bg.group_name ASC
        """)
        inventory_data = cursor.fetchall()
    except Error as e:
        flash(f"Database error loading inventory: {e}", "danger")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return render_template('inventory.html', inventory=inventory_data, blood_groups=blood_groups)

# --- Public Availability Route ---
@app.route('/check_availability')
def check_availability():
    """Displays the public-facing blood availability page."""
    conn = None
    cursor = None
    inventory_data = []

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # Join to get group_name for display
        cursor.execute("""
            SELECT i.units_available, bg.group_name 
            FROM inventory i
            JOIN blood_groups bg ON i.blood_group_id = bg.id
            WHERE i.units_available > 0 
            ORDER BY bg.group_name ASC
        """)
        inventory_data = cursor.fetchall()
    except Error as e:
        flash(f"Database error loading blood availability: {e}", "danger")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    
    return render_template('check_availability.html', inventory=inventory_data)


# --- Public Blood Request Form Route ---
@app.route('/public_add_blood_request', methods=['GET', 'POST'])
def public_add_blood_request():
    """Allows public users to submit a blood request."""
    blood_groups = get_all_blood_groups() # Fetch blood groups for dropdown

    if request.method == 'POST':
        patient_name = request.form['patient_name']
        blood_group_id = request.form['blood_group_id'] # Now get ID
        quantity_units = request.form['quantity_units']
        request_date = request.form['request_date']
        status = 'Pending' 
        reason = request.form.get('reason')
        requested_by = request.form.get('requested_by')

        conn = None
        cursor = None

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO blood_requests (patient_name, blood_group_id, quantity_units, request_date, status, reason, requested_by) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                           (patient_name, blood_group_id, quantity_units, request_date, status, reason, requested_by))
            conn.commit()
            flash("Your blood request has been submitted successfully! We will review it shortly.", "success")
            return redirect(url_for('check_availability'))
        except Error as e:
            flash(f"Error submitting request: {e}", "danger")
        finally:
            if cursor:
                cursor.close()
            if conn:
                    conn.close()
                
    return render_template('add_blood_request.html', blood_groups=blood_groups)


if __name__ == '__main__':
    app.run(debug=True)
