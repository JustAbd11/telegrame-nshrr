from flask import Flask, render_template, request, redirect, session
from werkzeug.security import generate_password_hash, check_password_hash
from supabase import create_client
from dotenv import load_dotenv
import os

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

@app.route("/")
def home():
    if "user_id" in session:
        return redirect("/dashboard")
    return redirect("/login")

@app.route("/register", methods=["GET","POST"])
def register():

    if request.method == "POST":

        email = request.form["email"]
        password = request.form["password"]

        hashed = generate_password_hash(password)

        supabase.table("users").insert({
            "email": email,
            "password_hash": hashed,
            "plan": "free"
        }).execute()

        return redirect("/login")

    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():

    if request.method == "POST":

        email = request.form["email"]
        password = request.form["password"]

        result = supabase.table("users")\
            .select("*")\
            .eq("email", email)\
            .execute()

        if len(result.data) > 0:

            user = result.data[0]

            if check_password_hash(
                user["password_hash"],
                password
            ):
                session["user_id"] = user["id"]
                session["email"] = user["email"]

                return redirect("/dashboard")

        return "بيانات الدخول غير صحيحة"

    return render_template("login.html")

@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:
        return redirect("/login")

    return render_template(
        "dashboard.html",
        email=session["email"]
    )

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

if __name__ == "__main__":
    app.run(debug=True)
