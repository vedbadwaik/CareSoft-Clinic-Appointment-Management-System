from fastapi import FastAPI, Depends, Form, HTTPException, status, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime, date
import os

from database import Base, engine, get_db, SessionLocal
from models import User, Patient, Doctor, Appointment, MedicalRecord, ReminderLog
from auth import create_token, verify_password, get_password_hash, get_current_user, RoleChecker

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="CareSoft Clinic Appointment Management System")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "frontend"))

# DB Seeding logic
def seed_db(db: Session):
    # Check if admin user exists (handling schema migration from older flat database structure)
    try:
        admin_exists = db.query(User).filter(User.role == "admin").first()
    except Exception:
        db.rollback()
        # Clear existing tables if any, to ensure consistent relational setup
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        admin_exists = None

    if not admin_exists:
        
        # 1. Seed Admin
        admin_user = User(
            name="System Administrator",
            email="admin@caresoft.com",
            password=get_password_hash("Admin@12345"),
            role="admin"
        )
        db.add(admin_user)
        
        # 2. Seed Doctors
        doctors_data = [
            ("Dr. Sarah Jenkins", "sarah.j@caresoft.com", "Cardiology", "MD, FACC"),
            ("Dr. Michael Chang", "michael.c@caresoft.com", "Pediatrics", "MD, FAAP"),
            ("Dr. Amina Yusuf", "amina.y@caresoft.com", "General Medicine", "MBBS"),
            ("Dr. Liam O'Connor", "liam.o@caresoft.com", "Dermatology", "MD")
        ]
        for name, email, spec, qual in doctors_data:
            doc_user = User(
                name=name,
                email=email,
                password=get_password_hash("Doctor@12345"),
                role="doctor"
            )
            db.add(doc_user)
            db.flush() # Populate doc_user.id
            
            doc_profile = Doctor(
                user_id=doc_user.id,
                phone="555-0101",
                specialization=spec,
                qualification=qual,
                available_days="Monday,Tuesday,Wednesday,Thursday,Friday",
                available_time_slots="09:00,10:00,11:00,14:00,15:00"
            )
            db.add(doc_profile)
            
        # 3. Seed Patient
        patient_user = User(
            name="John Doe",
            email="patient@caresoft.com",
            password=get_password_hash("Patient@12345"),
            role="patient"
        )
        db.add(patient_user)
        db.flush()
        
        patient_profile = Patient(
            user_id=patient_user.id,
            age=30,
            gender="Male",
            phone="555-1234",
            address="123 Main St",
            medical_notes="No known allergies"
        )
        db.add(patient_profile)
        db.commit()
        print("Database initialized and seeded successfully.")

# Initial Database Setup and Seeding
@app.on_event("startup")
def startup_populate():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_db(db)

# Automated reminder helper
def create_reminder_simulation(db: Session, appointment: Appointment):
    patient_name = appointment.patient.user.name
    doctor_name = appointment.doctor.user.name
    message = f"Hello {patient_name}, this is a reminder for your upcoming appointment with {doctor_name} on {appointment.date} at {appointment.time}."
    
    log = ReminderLog(
        appointment_id=appointment.id,
        reminder_type="Console",
        status="Sent",
        sent_at=datetime.now().isoformat(),
        message=message
    )
    db.add(log)
    db.commit()
    print(f"\n========================================\n[REMINDER SIMULATION]\nType: Console\nTo: {patient_name}\nMessage: {message}\n========================================\n")


# ==========================================
# AUTHENTICATION API ROUTES
# ==========================================

@app.post("/register")
def register(
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form("patient"),
    db: Session = Depends(get_db)
):
    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        return JSONResponse(status_code=400, content={"message": "Email already exists"})
    
    new_user = User(
        name=name,
        email=email,
        password=get_password_hash(password),
        role=role
    )
    db.add(new_user)
    db.flush()

    if role == "patient":
        patient_profile = Patient(
            user_id=new_user.id,
            age=None,
            gender=None,
            phone=None,
            address=None,
            medical_notes=""
        )
        db.add(patient_profile)
    elif role == "doctor":
        doctor_profile = Doctor(
            user_id=new_user.id,
            phone=None,
            specialization="General Medicine",
            qualification=None,
            available_days="Monday,Tuesday,Wednesday,Thursday,Friday",
            available_time_slots="09:00,10:00,11:00,14:00,15:00"
        )
        db.add(doctor_profile)

    db.commit()
    return {"message": "User Registered Successfully"}

@app.post("/login")
def login(
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password):
        return JSONResponse(status_code=401, content={"message": "Invalid Email or Password"})
    
    token = create_token(user.email, user.role)
    
    # Set httponly cookie for session rendering support
    response.set_cookie(
        key="access_token",
        value=f"Bearer {token}",
        httponly=True,
        max_age=86400,
        samesite="lax"
    )
    
    return {
        "access_token": token,
        "name": user.name,
        "email": user.email,
        "role": user.role
    }

@app.post("/logout")
def api_logout(response: Response):
    response.delete_cookie("access_token")
    return {"message": "Logged out successfully"}


# ==========================================
# PATIENT MANAGEMENT API ROUTES
# ==========================================

@app.put("/api/patients/profile")
def update_patient_profile(
    age: int = Form(...),
    gender: str = Form(...),
    phone: str = Form(...),
    address: str = Form(...),
    medical_notes: str = Form(""),
    current_user: User = Depends(RoleChecker(["patient"])),
    db: Session = Depends(get_db)
):
    patient = db.query(Patient).filter(Patient.user_id == current_user.id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found.")
        
    patient.age = age
    patient.gender = gender
    patient.phone = phone
    patient.address = address
    patient.medical_notes = medical_notes
    db.commit()
    return {"message": "Profile updated successfully"}


# ==========================================
# DOCTOR MANAGEMENT API ROUTES (ADMIN ONLY)
# ==========================================

@app.get("/api/doctors")
def get_doctors(db: Session = Depends(get_db)):
    doctors = db.query(Doctor).all()
    return [{
        "id": d.id,
        "name": d.user.name,
        "email": d.user.email,
        "phone": d.phone,
        "specialization": d.specialization,
        "qualification": d.qualification,
        "available_days": d.available_days,
        "available_time_slots": d.available_time_slots
    } for d in doctors]

@app.post("/api/doctors")
def create_doctor(
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    phone: str = Form(...),
    specialization: str = Form(...),
    qualification: str = Form(...),
    available_days: str = Form("Monday,Tuesday,Wednesday,Thursday,Friday"),
    available_time_slots: str = Form("09:00,10:00,11:00,14:00,15:00"),
    current_user: User = Depends(RoleChecker(["admin"])),
    db: Session = Depends(get_db)
):
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="User with this email already exists.")
        
    doc_user = User(
        name=name,
        email=email,
        password=get_password_hash(password),
        role="doctor"
    )
    db.add(doc_user)
    db.flush()
    
    doc_profile = Doctor(
        user_id=doc_user.id,
        phone=phone,
        specialization=specialization,
        qualification=qualification,
        available_days=available_days,
        available_time_slots=available_time_slots
    )
    db.add(doc_profile)
    db.commit()
    return {"message": "Doctor created successfully"}

@app.put("/api/doctors/{doctor_id}")
def update_doctor(
    doctor_id: int,
    phone: str = Form(...),
    specialization: str = Form(...),
    qualification: str = Form(...),
    available_days: str = Form(...),
    available_time_slots: str = Form(...),
    current_user: User = Depends(RoleChecker(["admin", "doctor"])),
    db: Session = Depends(get_db)
):
    doc = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Doctor profile not found.")
        
    # Check permissions (Doctor can only update their own profile; Admin can update any)
    if current_user.role == "doctor" and doc.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to edit this profile.")
        
    doc.phone = phone
    doc.specialization = specialization
    doc.qualification = qualification
    doc.available_days = available_days
    doc.available_time_slots = available_time_slots
    db.commit()
    return {"message": "Doctor profile updated successfully"}

@app.delete("/api/doctors/{doctor_id}")
def delete_doctor(
    doctor_id: int,
    current_user: User = Depends(RoleChecker(["admin"])),
    db: Session = Depends(get_db)
):
    doc = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Doctor not found.")
    
    user = doc.user
    db.delete(user) # Cascades to doctor record
    db.commit()
    return {"message": "Doctor deleted successfully"}


# ==========================================
# APPOINTMENT MANAGEMENT API ROUTES
# ==========================================

@app.get("/appointments")
def get_appointments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role == "patient":
        patient = db.query(Patient).filter(Patient.user_id == current_user.id).first()
        appointments = db.query(Appointment).filter(Appointment.patient_id == patient.id).all()
    elif current_user.role == "doctor":
        doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
        appointments = db.query(Appointment).filter(Appointment.doctor_id == doctor.id).all()
    else: # Admin
        appointments = db.query(Appointment).all()
        
    return [{
        "id": app.id,
        "patient_name": app.patient.user.name,
        "doctor_name": app.doctor.user.name,
        "date": app.date,
        "time": app.time,
        "status": app.status
    } for app in appointments]

@app.post("/book")
def book_appointment(
    patient_name: str = Form(...),
    doctor_id: int = Form(...),
    date: str = Form(...),
    time: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 1. Fetch booking Patient
    if current_user.role == "patient":
        patient = db.query(Patient).filter(Patient.user_id == current_user.id).first()
    else:
        # Admin can book on behalf of any patient by patient name, or we select the first patient matching name
        patient_user = db.query(User).filter(User.name == patient_name, User.role == "patient").first()
        if not patient_user:
            raise HTTPException(status_code=400, detail="Specified patient not found.")
        patient = patient_user.patient

    # 2. Fetch doctor
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found.")

    # 3. Validate Date is not in past
    try:
        booking_date = datetime.strptime(date, "%Y-%m-%d").date()
        if booking_date < datetime.today().date():
            raise HTTPException(status_code=400, detail="Cannot book appointments in the past.")
        day_name = booking_date.strftime("%A")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    # 4. Validate doctor available day
    available_days = [d.strip() for d in doctor.available_days.split(",") if d.strip()]
    if day_name not in available_days:
        raise HTTPException(status_code=400, detail=f"Doctor {doctor.user.name} is not available on {day_name}.")

    # 5. Validate doctor available slot
    available_slots = [t.strip() for t in doctor.available_time_slots.split(",") if t.strip()]
    if time not in available_slots:
        raise HTTPException(status_code=400, detail=f"Time slot {time} is not available. Available slots: {doctor.available_time_slots}")

    # 6. Check Doctor double booking
    conflict = db.query(Appointment).filter(
        Appointment.doctor_id == doctor_id,
        Appointment.date == date,
        Appointment.time == time,
        Appointment.status != "Cancelled"
    ).first()
    if conflict:
        raise HTTPException(status_code=400, detail="This time slot has already been booked with the doctor.")

    # 7. Check Patient conflict
    patient_conflict = db.query(Appointment).filter(
        Appointment.patient_id == patient.id,
        Appointment.date == date,
        Appointment.time == time,
        Appointment.status != "Cancelled"
    ).first()
    if patient_conflict:
        raise HTTPException(status_code=400, detail="You already have an appointment scheduled at this exact time.")

    # 8. Create booking
    appointment = Appointment(
        patient_id=patient.id,
        doctor_id=doctor.id,
        date=date,
        time=time,
        status="Scheduled"
    )
    db.add(appointment)
    db.flush()
    
    # 9. Trigger Reminder
    create_reminder_simulation(db, appointment)
    db.commit()
    
    return {"message": "Appointment Booked"}

@app.delete("/appointments/{appointment_id}")
def cancel_appointment(
    appointment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found.")
        
    # Check permissions
    if current_user.role == "patient" and appointment.patient.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to cancel this appointment.")
    elif current_user.role == "doctor" and appointment.doctor.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to cancel this appointment.")

    # Update status to Cancelled
    appointment.status = "Cancelled"
    db.commit()
    return {"message": "Appointment cancelled"}

@app.post("/appointments/{appointment_id}/reschedule")
def reschedule_appointment(
    appointment_id: int,
    date: str = Form(...),
    time: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found.")
        
    # Check authorization
    if current_user.role == "patient" and appointment.patient.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to edit this appointment.")
    elif current_user.role == "doctor" and appointment.doctor.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to edit this appointment.")

    doctor = appointment.doctor
    
    # Validate date/time slots
    try:
        booking_date = datetime.strptime(date, "%Y-%m-%d").date()
        if booking_date < datetime.today().date():
            raise HTTPException(status_code=400, detail="Cannot book appointments in the past.")
        day_name = booking_date.strftime("%A")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format.")

    available_days = [d.strip() for d in doctor.available_days.split(",") if d.strip()]
    if day_name not in available_days:
        raise HTTPException(status_code=400, detail=f"Doctor is not available on {day_name}.")

    available_slots = [t.strip() for t in doctor.available_time_slots.split(",") if t.strip()]
    if time not in available_slots:
        raise HTTPException(status_code=400, detail="Time slot not available.")

    conflict = db.query(Appointment).filter(
        Appointment.doctor_id == doctor.id,
        Appointment.date == date,
        Appointment.time == time,
        Appointment.id != appointment_id,
        Appointment.status != "Cancelled"
    ).first()
    if conflict:
        raise HTTPException(status_code=400, detail="Time slot already booked with the doctor.")

    appointment.date = date
    appointment.time = time
    appointment.status = "Scheduled" # Reset status to Scheduled/Pending
    
    # Trigger new reminder simulation
    create_reminder_simulation(db, appointment)
    db.commit()
    return {"message": "Appointment rescheduled successfully"}


# ==========================================
# MEDICAL RECORDS API ROUTES
# ==========================================

@app.post("/api/medical-records")
def create_medical_record(
    patient_id: int = Form(...),
    diagnosis: str = Form(...),
    prescription: str = Form(""),
    notes: str = Form(""),
    visit_date: str = Form(...),
    current_user: User = Depends(RoleChecker(["doctor", "admin"])),
    db: Session = Depends(get_db)
):
    # Retrieve doctor associated with current user
    if current_user.role == "doctor":
        doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    else:
        # Admin selects the first doctor in system or needs a parameter.
        # We will use the first doctor for simple mapping if admin makes it.
        doctor = db.query(Doctor).first()

    record = MedicalRecord(
        patient_id=patient_id,
        doctor_id=doctor.id,
        diagnosis=diagnosis,
        prescription=prescription,
        notes=notes,
        visit_date=visit_date
    )
    db.add(record)
    db.commit()
    return {"message": "Medical record created successfully"}


# ==========================================
# REMINDER SERVICES & SYSTEM TRIGGER
# ==========================================

@app.post("/api/reminders/trigger")
def trigger_reminders(db: Session = Depends(get_db)):
    appointments = db.query(Appointment).filter(
        Appointment.status.in_(["Scheduled", "Confirmed"])
    ).all()
    
    count = 0
    for app in appointments:
        exists = db.query(ReminderLog).filter(ReminderLog.appointment_id == app.id).first()
        if not exists:
            create_reminder_simulation(db, app)
            count += 1
            
    return {"message": f"Scanned upcoming appointments. Triggered {count} new reminders."}

@app.get("/api/reminders/logs")
def view_reminder_logs(
    current_user: User = Depends(RoleChecker(["admin"])),
    db: Session = Depends(get_db)
):
    logs = db.query(ReminderLog).order_by(ReminderLog.sent_at.desc()).all()
    return [{
        "id": l.id,
        "patient": l.appointment.patient.user.name,
        "doctor": l.appointment.doctor.user.name,
        "type": l.reminder_type,
        "status": l.status,
        "sent_at": l.sent_at,
        "message": l.message
    } for l in logs]


# ==========================================
# ROLE-BASED DASHBOARD METRICS API
# ==========================================

@app.get("/api/dashboard/admin")
def get_admin_stats(db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(["admin"]))):
    total_patients = db.query(Patient).count()
    total_doctors = db.query(Doctor).count()
    total_appointments = db.query(Appointment).count()
    upcoming_appointments = db.query(Appointment).filter(Appointment.status.in_(["Scheduled", "Confirmed"])).count()
    completed_appointments = db.query(Appointment).filter(Appointment.status == "Completed").count()
    
    doctors = [{
        "id": d.id,
        "name": d.user.name,
        "email": d.user.email,
        "phone": d.phone,
        "specialization": d.specialization,
        "qualification": d.qualification,
        "available_days": d.available_days,
        "available_time_slots": d.available_time_slots
    } for d in db.query(Doctor).all()]
        
    patients = [{
        "id": p.id,
        "name": p.user.name,
        "email": p.user.email,
        "age": p.age,
        "gender": p.gender,
        "phone": p.phone,
        "address": p.address,
        "medical_notes": p.medical_notes
    } for p in db.query(Patient).all()]
        
    users = [{
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "role": u.role
    } for u in db.query(User).all()]

    return {
        "stats": {
            "total_patients": total_patients,
            "total_doctors": total_doctors,
            "total_appointments": total_appointments,
            "upcoming_appointments": upcoming_appointments,
            "completed_appointments": completed_appointments
        },
        "doctors": doctors,
        "patients": patients,
        "users": users
    }

@app.get("/api/dashboard/doctor")
def get_doctor_stats(db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(["doctor"]))):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found.")
        
    today_str = date.today().isoformat()
    
    today_appointments = []
    upcoming_appointments = []
    past_appointments = []
    
    appointments = db.query(Appointment).filter(Appointment.doctor_id == doctor.id).all()
    for app in appointments:
        app_data = {
            "id": app.id,
            "patient_name": app.patient.user.name,
            "date": app.date,
            "time": app.time,
            "status": app.status
        }
        if app.date == today_str and app.status in ["Scheduled", "Confirmed"]:
            today_appointments.append(app_data)
        elif app.date >= today_str and app.status in ["Scheduled", "Confirmed"]:
            upcoming_appointments.append(app_data)
        else:
            past_appointments.append(app_data)
            
    # Distinct patients who visited this doctor
    patient_ids = db.query(Appointment.patient_id).filter(Appointment.doctor_id == doctor.id).distinct().all()
    patients_history = []
    for (p_id,) in patient_ids:
        p = db.query(Patient).filter(Patient.id == p_id).first()
        if p:
            records = db.query(MedicalRecord).filter(MedicalRecord.patient_id == p_id, MedicalRecord.doctor_id == doctor.id).all()
            patients_history.append({
                "id": p.id,
                "name": p.user.name,
                "age": p.age,
                "gender": p.gender,
                "phone": p.phone,
                "medical_notes": p.medical_notes,
                "records": [{
                    "id": r.id,
                    "visit_date": r.visit_date,
                    "diagnosis": r.diagnosis,
                    "prescription": r.prescription,
                    "notes": r.notes
                } for r in records]
            })

    return {
        "doctor_profile": {
            "id": doctor.id,
            "name": current_user.name,
            "email": current_user.email,
            "phone": doctor.phone,
            "specialization": doctor.specialization,
            "qualification": doctor.qualification,
            "available_days": doctor.available_days,
            "available_time_slots": doctor.available_time_slots
        },
        "today_appointments": today_appointments,
        "upcoming_appointments": upcoming_appointments,
        "past_appointments": past_appointments,
        "patient_history": patients_history
    }

@app.get("/api/dashboard/patient")
def get_patient_stats(db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(["patient"]))):
    patient = db.query(Patient).filter(Patient.user_id == current_user.id).first()
    if not patient:
        patient = Patient(user_id=current_user.id)
        db.add(patient)
        db.commit()
        db.refresh(patient)
        
    today_str = date.today().isoformat()
    
    upcoming_visits = []
    history = []
    
    appointments = db.query(Appointment).filter(Appointment.patient_id == patient.id).all()
    for app in appointments:
        app_data = {
            "id": app.id,
            "doctor_name": app.doctor.user.name,
            "specialization": app.doctor.specialization,
            "date": app.date,
            "time": app.time,
            "status": app.status
        }
        if app.date >= today_str and app.status in ["Scheduled", "Confirmed"]:
            upcoming_visits.append(app_data)
        else:
            history.append(app_data)
            
    records = db.query(MedicalRecord).filter(MedicalRecord.patient_id == patient.id).all()
    medical_records = [{
        "id": r.id,
        "doctor_name": r.doctor.user.name,
        "specialization": r.doctor.specialization,
        "visit_date": r.visit_date,
        "diagnosis": r.diagnosis,
        "prescription": r.prescription,
        "notes": r.notes
    } for r in records]
    
    return {
        "patient_profile": {
            "id": patient.id,
            "name": current_user.name,
            "email": current_user.email,
            "phone": patient.phone,
            "age": patient.age,
            "gender": patient.gender,
            "address": patient.address,
            "medical_notes": patient.medical_notes
        },
        "upcoming_visits": upcoming_visits,
        "appointment_history": history,
        "medical_records": medical_records
    }


# ==========================================
# PAGE ROUTING (HTML RENDERING)
# ==========================================

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/register-page", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse(request=request, name="register.html")

@app.get("/login-page", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")

@app.get("/book-page", response_class=HTMLResponse)
def book_page(request: Request):
    return templates.TemplateResponse(request=request, name="book.html")

@app.get("/appointments-page", response_class=HTMLResponse)
def appointments_page(request: Request):
    return templates.TemplateResponse(request=request, name="appointments.html")

@app.get("/dashboard-page", response_class=HTMLResponse)
def dashboard_page(request: Request):
    return templates.TemplateResponse(request=request, name="dashboard.html")