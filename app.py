from flask import Flask, render_template, request, session, make_response, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import pdfkit
import pandas as pd
from datetime import datetime
from pytz import timezone
from werkzeug.security import generate_password_hash, check_password_hash
import random

from groq import Groq
import os
from dotenv import load_dotenv
from flask import request, render_template
import requests

# Load environment variables
load_dotenv()

# Initialize Groq client
client = Groq(api_key=os.environ.get("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"))  # Make sure key is in .env

IST = timezone('Asia/Kolkata')

app = Flask(__name__)
app.secret_key = '1225'

# Database config
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Login Manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Configure pdfkit
try:
    pdfkit.from_string('test', False)
    config = None
except OSError:
    # Update path if needed
    config = pdfkit.configuration(wkhtmltopdf='C:/Program Files/wkhtmltopdf/bin/wkhtmltopdf.exe')

# Load your food nutrition dataset
df = pd.read_csv('Indian_Food_Nutrition_Processed.csv')

# User Model
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    email = db.Column(db.String(100), unique=True)
    password_hash = db.Column(db.String(200))
    age = db.Column(db.Integer)
    gender = db.Column(db.String(10))
    weight = db.Column(db.Float)
    height = db.Column(db.Float)
    activity = db.Column(db.String(20))
    goal = db.Column(db.String(10))
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(IST))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# MealPlan Model
class MealPlan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    day = db.Column(db.String(10))  # Day 1, Day 2, etc.
    meal = db.Column(db.String(20))
    dish_name = db.Column(db.String(100))
    calories = db.Column(db.Float)
    protein = db.Column(db.Float)
    fats = db.Column(db.Float)
    carbs = db.Column(db.Float)
    user = db.relationship('User', backref='meal_plans')






@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/home')
def homepage():
    return render_template('home.html', current_user=current_user)


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']

        if User.query.filter_by(email=email).first():
            return "Email already registered. <a href='/login'>Login</a>"

        user = User(name=name, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        return redirect('/login')

    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            login_user(user)
            session.pop('weekly_plan', None)
            session.pop('total_days', None)
            return redirect('/profile')
        else:
            return "Invalid credentials. <a href='/login'>Try again</a>"

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/')

@app.route('/profile')
@login_required
def profile():
    # Check if user has any saved weekly meal plans in DB
    has_plan = MealPlan.query.filter_by(user_id=current_user.id, day="Day 1").first() is not None
    return render_template('profile.html', current_user=current_user, has_plan=has_plan)


@app.route('/recommend', methods=['POST'])
@login_required
def recommend():
    # Get user data from form
    age = int(request.form['age'])
    gender = request.form['gender']
    weight = float(request.form['weight'])
    height = float(request.form['height'])
    activity = request.form['activity']
    goal = request.form['goal']

    # Save to user
    current_user.age = age
    current_user.gender = gender
    current_user.weight = weight
    current_user.height = height
    current_user.activity = activity
    current_user.goal = goal
    db.session.commit()

    # Auto-correct height if entered in meters
    if height < 10:
        height = height * 100

    # BMR Calculation (Mifflin-St Jeor)
    if gender == 'male':
        bmr = 10 * weight + 6.25 * height - 5 * age + 5
    else:
        bmr = 10 * weight + 6.25 * height - 5 * age - 161

    # Activity factor lookup
    activity_factors = {
        'sedentary': 1.2,
        'lightly': 1.375,
        'moderately': 1.55,
        'very': 1.725,
        'extra': 1.9
    }
    tdee = bmr * activity_factors[activity]

    # Adjust for goal
    if goal == 'lose':
        calorie_target = tdee - 400
    elif goal == 'gain':
        calorie_target = tdee + 400
    else:
        calorie_target = tdee

    # Calculate BMI
    bmi = weight / ((height / 100) ** 2)
    if bmi < 18.5:
        bmi_status = "Underweight"
    elif bmi < 25:
        bmi_status = "Healthy"
    elif bmi < 30:
        bmi_status = "Overweight"
    else:
        bmi_status = "Obese"

    # Split into meals
    meals = {
        'Breakfast': calorie_target * 0.25,
        'Lunch': calorie_target * 0.35,
        'Snack': calorie_target * 0.15,
        'Dinner': calorie_target * 0.25
    }

    # Get dietary preferences
    is_vegetarian = request.form.get('vegetarian') == 'yes'
    is_vegan = request.form.get('vegan') == 'yes'
    is_diabetic = request.form.get('diabetic') == 'yes'

    # Start with full dataset
    filtered_df = df.copy()

    # Apply filters
    if is_vegetarian and 'is_vegetarian' in filtered_df.columns:
        filtered_df = filtered_df[filtered_df['is_vegetarian'] == True]
    if is_vegan and 'is_vegan' in filtered_df.columns:
        filtered_df = filtered_df[filtered_df['is_vegan'] == True]
    if is_diabetic:
        filtered_df = filtered_df[filtered_df['Free Sugar (g)'] < 10]

    # Check if user wants weekly plan
    generate_weekly = request.form.get('weekly') == 'yes'

    MealPlan.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()


    # Generate plan
    if generate_weekly:
        weekly_plan = {}
        total_week_protein = 0
        total_week_carbs = 0
        total_week_fats = 0

        for day_num in range(1, 8):
            daily_plan = {}
            variation = 0.97 + (random.random() * 0.06)
            for meal, cal in meals.items():
                adjusted_cal = cal * variation
                meal_foods = filtered_df[abs(filtered_df['Calories (kcal)'] - adjusted_cal / 3) < 100]
                if len(meal_foods) == 0:
                    meal_foods = filtered_df.nsmallest(3, 'Calories (kcal)')
                daily_plan[meal] = meal_foods.sample(3)[[
                    'Dish Name', 'Calories (kcal)', 'Protein (g)', 'Fats (g)', 'Carbohydrates (g)'
                ]].to_dict('records')

                for food in daily_plan[meal]:
                    total_week_protein += food['Protein (g)']
                    total_week_carbs += food['Carbohydrates (g)']
                    total_week_fats += food['Fats (g)']

            weekly_plan[f'Day {day_num}'] = daily_plan

        # Save to session
        session['pdf_data'] = {
            'target': int(calorie_target),
            'bmi': round(bmi, 1),
            'bmi_status': bmi_status,
            'plan': weekly_plan,
            'total_protein': round(total_week_protein, 1),
            'total_carbs': round(total_week_carbs, 1),
            'total_fats': round(total_week_fats, 1),
            'is_weekly': True
        }

        # ✅ Save weekly plan separately for reliable access
        session['weekly_plan'] = weekly_plan
        session['total_days'] = len(weekly_plan)

        # Save to DB
        try:
            for day, meals_data in weekly_plan.items():
                for meal, foods in meals_data.items():
                    for food in foods:
                        meal_entry = MealPlan(
                            user_id=current_user.id,
                            day=day,
                            meal=meal,
                            dish_name=food['Dish Name'],
                            calories=food['Calories (kcal)'],
                            protein=food['Protein (g)'],
                            fats=food['Fats (g)'],
                            carbs=food['Carbohydrates (g)']
                        )
                        db.session.add(meal_entry)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Database error: {str(e)}")

        return redirect('/day/1')

    else:
        recommendations = {}
        for meal, cal in meals.items():
            meal_foods = filtered_df[abs(filtered_df['Calories (kcal)'] - cal / 3) < 100]
            if len(meal_foods) == 0:
                meal_foods = filtered_df.nsmallest(3, 'Calories (kcal)')
            recommendations[meal] = meal_foods.sample(3)[[
                'Dish Name', 'Calories (kcal)', 'Protein (g)', 'Fats (g)', 'Carbohydrates (g)'
            ]].to_dict('records')

        total_protein = sum(food['Protein (g)'] for foods in recommendations.values() for food in foods)
        total_carbs = sum(food['Carbohydrates (g)'] for foods in recommendations.values() for food in foods)
        total_fats = sum(food['Fats (g)'] for foods in recommendations.values() for food in foods)

        session['pdf_data'] = {
            'target': int(calorie_target),
            'bmi': round(bmi, 1),
            'bmi_status': bmi_status,
            'plan': recommendations,
            'total_protein': round(total_protein, 1),
            'total_carbs': round(total_carbs, 1),
            'total_fats': round(total_fats, 1),
            'is_weekly': False
        }

        try:
            for meal, foods in recommendations.items():
                for food in foods:
                    meal_entry = MealPlan(
                        user_id=current_user.id,
                        day='Day 1',
                        meal=meal,
                        dish_name=food['Dish Name'],
                        calories=food['Calories (kcal)'],
                        protein=food['Protein (g)'],
                        fats=food['Fats (g)'],
                        carbs=food['Carbohydrates (g)']
                    )
                    db.session.add(meal_entry)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Database error: {str(e)}")

        return render_template(
            'result.html',
            target=int(calorie_target),
            plan=recommendations,
            bmi=round(bmi, 1),
            bmi_status=bmi_status,
            total_protein=round(total_protein, 1),
            total_carbs=round(total_carbs, 1),
            total_fats=round(total_fats, 1)
        )

@app.route('/day/<int:day_num>')
@login_required
def view_day(day_num):
    day_key = f"Day {day_num}"

    # Get list of distinct days planned for user
    all_days = db.session.query(MealPlan.day).filter_by(user_id=current_user.id).distinct().all()
    total_days = len(all_days)

    if day_num < 1 or day_num > total_days:
        return "Invalid day number.", 404

    # Fetch meal plans for the day and user
    day_meals = MealPlan.query.filter_by(user_id=current_user.id, day=day_key).all()
    if not day_meals:
        return "No weekly plan found. Please generate one first.", 400

    # Organize meals by type, limit to 3 dishes each
    plan = {}
    for meal_name in ['Breakfast', 'Lunch', 'Snack', 'Dinner']:
        meal_list = [mp for mp in day_meals if mp.meal == meal_name]
        plan[meal_name] = meal_list[:3]  # Limit to 3 dishes per meal

    return render_template('day.html',
                           day_num=day_num,
                           day_name=day_key,
                           plan=plan,
                           total_days=total_days)


@app.route('/pdf')
@login_required
def pdf():
    path_wkhtmltopdf = r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe'  # Change accordingly
    config = pdfkit.configuration(wkhtmltopdf=path_wkhtmltopdf)

    # Fetch distinct days for this user
    days = db.session.query(MealPlan.day).filter_by(user_id=current_user.id).distinct().all()
    days = [d[0] for d in days]

    if not days:
        return "No data found. Please generate a meal plan first.", 400

    weekly_plan_data = {}
    for day in days:
        meals = MealPlan.query.filter_by(user_id=current_user.id, day=day).all()
        daily_meals = {}
        for meal_type in ["Breakfast", "Lunch", "Snack", "Dinner"]:
            daily_meals[meal_type] = [m for m in meals if m.meal == meal_type]
        weekly_plan_data[day] = daily_meals

    rendered = render_template("pdf.html", plan=weekly_plan_data)

    try:
        pdf = pdfkit.from_string(rendered, False, configuration=config)
    except Exception as e:
        return f"PDF generation failed: {str(e)}", 500

    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'attachment; filename=HealthMateDietPlan.pdf'
    return response



@app.route('/chatbot')
@login_required
def chatbot_page():
    return render_template('chatbot.html')




@app.route('/chatbot', methods=['POST'])
@login_required
def chatbot():
    user_message = request.json.get('message')
    
    if not user_message or not user_message.strip():
        return {"response": "Please ask a valid question."}
    
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are NutriPal, a friendly and supportive Indian diet assistant. "
                        "Talk like a caring friend who knows nutrition. "
                        "Use Indian examples: roti, dal, curd, sprouts, oats, ragi, etc. "
                        "Keep answers short (1-2 sentences), encouraging, and practical. "
                        "If asked about weight loss, say: 'Focus on portion control and walking daily!' "
                        "If asked about protein, say: 'Great sources: paneer, eggs, sprouts, and lentils!'"
                    )
                },
                {
                    "role": "user",
                    "content": user_message
                }
            ],
            model="llama-3.1-8b-instant",
            temperature=0.7,
            max_tokens=150
        )
        bot_response = chat_completion.choices[0].message.content
        return {"response": bot_response}
    except Exception as e:
        print("Error:", str(e))
        return {"response": "Sorry, I couldn't process your request. Please try again."}

@app.route('/progress', methods=['GET', 'POST'])
@login_required
def progress():
    if request.method == 'POST':
        weight = float(request.form['weight'])
        bmi = float(request.form['bmi'])
        calories = float(request.form['calories'])
        protein = float(request.form['protein'])
        carbs = float(request.form['carbs'])
        fats = float(request.form['fats'])

        progress_entry = UserHealthProgress(
            user_id=current_user.id,
            weight=weight,
            bmi=bmi,
            calories_consumed=calories,
            protein_consumed=protein,
            carbs_consumed=carbs,
            fats_consumed=fats,
            date=datetime.utcnow()
        )
        db.session.add(progress_entry)
        db.session.commit()
        return redirect(url_for('progress'))

    # On GET, show user's progress history
    progress_data = UserHealthProgress.query.filter_by(user_id=current_user.id).order_by(UserHealthProgress.date).all()
    return render_template('progress.html', progress_data=progress_data)


@app.route('/external-recipes', methods=['GET', 'POST'])
def external_recipes():
    recipes = []
    if request.method == 'POST':
        keywords = [kw.strip() for kw in request.form['keywords'].split(',')]
        recipes = fetch_recipes_from_spoonacular(keywords)
    return render_template('external_recipes.html', recipes=recipes)


def fetch_recipes_from_spoonacular(keywords):
    api_key = "beafddd4a3d84202a93f65f5bed56b8b"  # Replace with your actual key
    query = ",".join(keywords)
    url = f"https://api.spoonacular.com/recipes/complexSearch?includeIngredients={query}&number=10&apiKey={api_key}"

    response = requests.get(url)
    data = response.json()
    recipes = []
    if 'results' in data:
        for item in data['results']:
            recipes.append({
                'id': item['id'],
                'title': item['title'],
                'image': item.get('image', None)
            })
    return recipes



if __name__ == '__main__':
    app.run(debug=True)
