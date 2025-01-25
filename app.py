# app.py

from flask import Flask, render_template, request, redirect, url_for, send_file, flash, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from sqlalchemy import UniqueConstraint, func
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, FloatField, SubmitField, DateField, RadioField, IntegerField, BooleanField, SelectMultipleField
from wtforms.validators import DataRequired, NumberRange, ValidationError, Optional
import unicodedata
import csv
import io
import os
import json
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key_here'  # Replace with a strong secret key
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chess_tournament.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'  # Redirect to this view if not authenticated

# Database Models
class User(UserMixin, db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)  # Store hashed passwords

class Player(db.Model):
    __tablename__ = 'player'
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    
    __table_args__ = (
        UniqueConstraint('first_name', 'last_name', name='uix_first_last_name'),
    )
    # The 'points' relationship is defined via backref in Point

class Tournament(db.Model):
    __tablename__ = 'tournament'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)  # Assuming each tournament date is unique
    # The 'points' relationship is defined via backref in Point

class Point(db.Model):
    __tablename__ = 'point'
    id = db.Column(db.Integer, primary_key=True)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    points = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(1), nullable=False)  # 'A' or 'B'

    # Relationships
    player = db.relationship('Player', backref=db.backref('points', lazy=True))
    tournament = db.relationship('Tournament', backref=db.backref('points', lazy='dynamic', cascade="all, delete-orphan"))
    
    __table_args__ = (
        UniqueConstraint('player_id', 'tournament_id', name='uix_player_tournament'),
    )

# User Loader for Flask-Login
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Custom Validator
def HalfStepCheck(form, field):
    """
    Validates that the input is a multiple of 0.5.
    """
    try:
        value = float(field.data)
    except (ValueError, TypeError):
        raise ValidationError('Invalid number.')

    if (value * 2) % 1 != 0:
        raise ValidationError('Points must be in 0.5 increments.')

# Forms
class PlayerForm(FlaskForm):
    first_name = StringField('First Name', validators=[DataRequired()])
    last_name = StringField('Last Name', validators=[DataRequired()])
    submit = SubmitField('Add Player')

class TournamentForm(FlaskForm):
    date = DateField('Date', validators=[DataRequired()])
    submit = SubmitField('Add Tournament')

class EditTournamentForm(FlaskForm):
    date = SelectField('Select Date', choices=[], coerce=int, validators=[DataRequired()])
    submit = SubmitField('Update Tournament')

class PointForm(FlaskForm):
    tournament = SelectField('Tournament', coerce=int, validators=[DataRequired()])
    player = SelectField('Player', coerce=int, validators=[DataRequired()])
    points = FloatField(
        'Points',
        validators=[
            DataRequired(),
            NumberRange(min=0),
            HalfStepCheck  # Attach the custom validator here
        ]
    )
    category = RadioField(
        'Category',
        choices=[('A', 'Category A'), ('B', 'Category B')],
        validators=[DataRequired()],
        default='A'  # Set a default selection
    )
    submit = SubmitField('Add Points')

class VisualizationForm(FlaskForm):
    visualization_type = RadioField(
        'Visualization Type',
        choices=[('tournament', 'Specific Tournament'), ('general', 'General Classification')],
        validators=[DataRequired()],
        default='tournament'
    )
    
    # Fields for Specific Tournament Visualization
    specific_tournament = SelectField('Select Tournament', coerce=int, validators=[Optional()])
    specific_top_n = IntegerField(
        'Number of Top Players',
        validators=[
            Optional(),
            NumberRange(min=1, max=20, message="Please select a number between 1 and 20.")
        ],
        default=5
    )
    
    # Fields for General Classification Visualization
    date_range = BooleanField('Filter by Date Range')
    start_date = DateField('Start Date', validators=[Optional()])
    end_date = DateField('End Date', validators=[Optional()])
    year = IntegerField('Year', validators=[Optional(), NumberRange(min=1900, max=2100, message="Enter a valid year.")])
    general_top_n = IntegerField(
        'Number of Top Players',
        validators=[
            Optional(),
            NumberRange(min=1, max=50, message="Please select a number between 1 and 50.")
        ],
        default=10
    )
    
    submit = SubmitField('Visualize')

class EditPlayerForm(FlaskForm):
    first_name = StringField(
        'First Name', 
        validators=[DataRequired()]
    )
    last_name = StringField(
        'Last Name', 
        validators=[DataRequired()]
    )
    submit = SubmitField('Save Changes')

# Utility Functions
def normalize_name(name):
    # Remove diacritics and special characters
    name = unicodedata.normalize('NFD', name)
    name = ''.join([c for c in name if unicodedata.category(c) != 'Mn'])
    # Remove non-alphabetic characters
    name = ''.join(filter(str.isalpha, name))
    # Capitalize first letter
    return name.capitalize()

def create_users_from_file(file_path='users.json'):
    """
    Creates users from a JSON file if they don't already exist in the database.
    The JSON file should contain a list of users with 'username' and 'password' fields.
    Passwords should be plaintext and will be hashed before storing.
    """
    if not os.path.exists(file_path):
        print(f"User file '{file_path}' not found.")
        return

    with open(file_path, 'r') as f:
        try:
            users = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from '{file_path}': {e}")
            return

    for user_data in users:
        username = user_data.get('username')
        password = user_data.get('password')

        if not username or not password:
            print(f"Invalid user data: {user_data}")
            continue

        existing_user = User.query.filter_by(username=username).first()
        if not existing_user:
            hashed_password = generate_password_hash(password, method='scrypt')
            new_user = User(username=username, password=hashed_password)
            db.session.add(new_user)
            print(f"Created user: {username}")
        else:
            print(f"User '{username}' already exists.")

    try:
        db.session.commit()
        print("User creation from file completed.")
    except IntegrityError as e:
        db.session.rollback()
        print(f"Error creating users: {e}")

# Routes
@app.route('/')
@login_required
def index():
    # Query to calculate total points for all players
    general_ranking = db.session.query(
        Player.first_name,
        Player.last_name,
        func.sum(Point.points).label('total_points')
    ).join(Point).group_by(Player.id).order_by(func.sum(Point.points).desc()).all()

    # Pass the ranking data to the template
    return render_template('index.html', general_ranking=general_ranking, enumerate=enumerate)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if not username or not password:
            flash('Please enter both username and password.', 'danger')
            return redirect(url_for('login'))
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash('Logged in successfully!', 'success')
            next_page = request.args.get('next')
            # Validate the redirect target to prevent open redirects
            if next_page and next_page.startswith('/'):
                return redirect(next_page)
            else:
                return redirect(url_for('index'))
        else:
            flash('Invalid username or password.', 'danger')
    
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))


@app.route('/export')
@login_required
def export_data():
    # Explicitly specify the FROM clause and joins
    data = db.session.query(
        Player.first_name,
        Player.last_name,
        Tournament.date.label('tournament_date'),
        Point.category,
        Point.points
    ).select_from(Point)\
     .join(Player, Point.player_id == Player.id)\
     .join(Tournament, Point.tournament_id == Tournament.id)\
     .order_by(Tournament.date).all()

    # Create a response object to serve the CSV
    def generate_csv():
        yield "First Name,Last Name,Tournament Date,Category,Points\n"  # Header
        for row in data:
            yield f"{row.first_name},{row.last_name},{row.tournament_date},{row.category},{row.points}\n"

    response = Response(generate_csv(), mimetype='text/csv')
    response.headers.set("Content-Disposition", "attachment", filename="database_export.csv")
    return response


@app.route('/export_page')
@login_required
def export_page():
    return render_template('export.html')


@app.route('/add_player', methods=['GET', 'POST'])
@login_required
def add_player():
    form = PlayerForm()
    if form.validate_on_submit():
        first_name = normalize_name(form.first_name.data)
        last_name = normalize_name(form.last_name.data)
        new_player = Player(first_name=first_name, last_name=last_name)
        try:
            db.session.add(new_player)
            db.session.commit()
            flash(f'Player added: {first_name} {last_name}', 'success')
            return redirect(url_for('add_player'))
        except IntegrityError:
            db.session.rollback()
            flash('Error adding player. The combination of first and last name must be unique.', 'danger')
    elif request.method == 'POST':
        flash('Please correct the errors in the form.', 'danger')
    return render_template('add_player.html', form=form)


@app.route('/add_tournament', methods=['GET', 'POST'])
@login_required
def add_tournament():
    form = TournamentForm()
    if form.validate_on_submit():
        date = form.date.data
        new_tournament = Tournament(date=date)
        try:
            db.session.add(new_tournament)
            db.session.commit()
            flash(f'Tournament added on: {date}', 'success')
            return redirect(url_for('add_tournament'))
        except IntegrityError:
            db.session.rollback()
            flash('Error adding tournament. The tournament date must be unique.', 'danger')
    elif request.method == 'POST':
        flash('Please correct the errors in the form.', 'danger')
    return render_template('add_tournament.html', form=form)


@app.route('/edit_tournament/<int:tournament_id>', methods=['GET', 'POST'])
@login_required
def edit_tournament(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    form = EditTournamentForm(obj=tournament)

    # Populate the dropdown with all tournament dates
    all_tournaments = Tournament.query.order_by(Tournament.date).all()
    form.date.choices = [(t.id, t.date.strftime('%Y-%m-%d')) for t in all_tournaments]

    if form.validate_on_submit():
        selected_tournament = Tournament.query.get(form.date.data)
        if selected_tournament:
            tournament.date = selected_tournament.date  # Update to selected date
            try:
                db.session.commit()
                flash('Tournament updated successfully.', 'success')
                return redirect(url_for('view_tournaments'))
            except IntegrityError:
                db.session.rollback()
                flash('Error updating tournament. The tournament date must be unique.', 'danger')
        else:
            flash('Selected tournament does not exist.', 'danger')
    elif request.method == 'POST':
        flash('Please correct the errors in the form.', 'danger')

    # Get players and scores in the tournament sorted by category and points
    players_scores = Point.query.filter_by(tournament_id=tournament_id)\
        .join(Player)\
        .order_by(Point.category.asc(), Point.points.desc()).all()

    return render_template(
        'edit_tournament.html',
        form=form,
        tournament=tournament,
        players_scores=players_scores
    )


@app.route('/edit_player/<int:player_id>', methods=['GET', 'POST'])
@login_required
def edit_player(player_id):
    player = Player.query.get_or_404(player_id)
    form = EditPlayerForm(obj=player)

    if form.validate_on_submit():
        player.first_name = normalize_name(form.first_name.data)
        player.last_name = normalize_name(form.last_name.data)
        try:
            db.session.commit()
            flash('Player updated successfully.', 'success')
            return redirect(url_for('view_players'))
        except IntegrityError:
            db.session.rollback()
            flash('Error updating player. Ensure the name is unique.', 'danger')

    return render_template('edit_player.html', form=form, player=player)


@app.route('/edit_player_score/<int:point_id>', methods=['POST'])
@login_required
def edit_player_score(point_id):
    point = Point.query.get_or_404(point_id)
    new_points = request.form.get('points', type=float)
    if new_points is not None:
        point.points = new_points
        try:
            db.session.commit()
            flash('Player score updated successfully.', 'success')
        except IntegrityError:
            db.session.rollback()
            flash('Error updating player score.', 'danger')
    else:
        flash('Invalid input for points.', 'danger')
    return redirect(request.referrer)


@app.route('/delete_player/<int:point_id>', methods=['POST'])
@login_required
def delete_player(point_id):
    point = Point.query.get_or_404(point_id)
    try:
        db.session.delete(point)
        db.session.commit()
        flash('Player removed from tournament successfully.', 'success')
    except IntegrityError:
        db.session.rollback()
        flash('Error removing player from tournament.', 'danger')
    return redirect(url_for('view_players'))


@app.route('/delete_tournament/<int:tournament_id>', methods=['POST'])
@login_required
def delete_tournament(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    try:
        db.session.delete(tournament)
        db.session.commit()
        flash('Tournament deleted successfully.', 'success')
        return redirect(url_for('view_tournaments'))
    except IntegrityError:
        db.session.rollback()
        flash('Error deleting tournament. Ensure that there are no associated points.', 'danger')
        return redirect(url_for('view_tournaments'))


@app.route('/edit_player_category/<int:point_id>', methods=['POST'])
@login_required
def edit_player_category(point_id):
    point = Point.query.get_or_404(point_id)
    new_category = request.form.get('category', type=str)
    if new_category in ['A', 'B']:  # Validate the category
        point.category = new_category
        try:
            db.session.commit()
            flash('Player category updated successfully.', 'success')
        except IntegrityError:
            db.session.rollback()
            flash('Error updating player category.', 'danger')
    else:
        flash('Invalid category selected.', 'danger')
    return redirect(request.referrer)


@app.route('/remove_player/<int:player_id>', methods=['POST'])
@login_required
def remove_player(player_id):
    player = Player.query.get_or_404(player_id)
    try:
        # Delete the player
        db.session.delete(player)
        db.session.commit()
        flash('Player removed successfully.', 'success')
    except IntegrityError:
        db.session.rollback()
        flash('Error removing player. Ensure all associated points are removed first.', 'danger')
    return redirect(url_for('view_players'))


@app.route('/view_players')
@login_required
def view_players():
    players = Player.query.order_by(Player.last_name, Player.first_name).all()
    return render_template('view_players.html', players=players)


@app.route('/view_tournaments')
@login_required
def view_tournaments():
    tournaments = Tournament.query.order_by(Tournament.date.desc()).all()
    return render_template('view_tournaments.html', tournaments=tournaments)


@app.route('/progression', methods=['GET', 'POST'])
@login_required
def progression():
    players = Player.query.order_by(Player.first_name, Player.last_name).all()
    player_choices = [(p.id, f"{p.first_name} {p.last_name}") for p in players]

    # Define the form dynamically
    class PlayerProgressionForm(FlaskForm):
        players = SelectMultipleField('Select Players', choices=player_choices, coerce=int, validators=[DataRequired()])
        submit = SubmitField('Show Progression')

    form = PlayerProgressionForm()

    progression_data = None
    if form.validate_on_submit():
        selected_player_ids = form.players.data

        # Query progression data
        query = (
            db.session.query(
                Player.first_name,
                Player.last_name,
                Tournament.date,
                func.sum(Point.points).label('total_points')
            )
            .join(Point, Point.player_id == Player.id)
            .join(Tournament, Tournament.id == Point.tournament_id)
            .filter(Player.id.in_(selected_player_ids))
            .group_by(Player.id, Tournament.date)
            .order_by(Tournament.date)
            .all()
        )

        # Organize progression data for the graph
        progression_data = {}
        for first_name, last_name, date, total_points in query:
            player_name = f"{first_name} {last_name}"
            if player_name not in progression_data:
                progression_data[player_name] = {"dates": [], "points": []}
            progression_data[player_name]["dates"].append(date.strftime('%Y-%m-%d'))
            progression_data[player_name]["points"].append(total_points)
    return render_template('progression.html', form=form, progression_data=progression_data)


@app.route('/add_points', methods=['GET', 'POST'])
@login_required
def add_points():
    form = PointForm()
    # Populate tournament and player choices
    tournaments = Tournament.query.order_by(Tournament.date.desc()).all()
    players = Player.query.order_by(Player.last_name, Player.first_name).all()
    
    form.tournament.choices = [(t.id, t.date.strftime('%Y-%m-%d')) for t in tournaments]
    form.player.choices = [(p.id, f'{p.first_name} {p.last_name}') for p in players]
    
    if form.validate_on_submit():
        tournament_id = form.tournament.data
        player_id = form.player.data
        points = form.points.data
        category = form.category.data
        new_point = Point(tournament_id=tournament_id, player_id=player_id, points=points, category=category)
        try:
            db.session.add(new_point)
            db.session.commit()
            flash('Points added successfully.', 'success')
            return redirect(url_for('add_points'))
        except IntegrityError:
            db.session.rollback()
            flash('Error adding points. Each player can have only one point entry per tournament.', 'danger')
    elif request.method == 'POST':
        flash('Please correct the errors in the form.', 'danger')
    return render_template('add_points.html', form=form)


@app.route('/view_results', methods=['GET', 'POST'])
@login_required
def view_results():
    tournaments = Tournament.query.order_by(Tournament.date.desc()).all()
    selected_tournament = None
    category_a_results = []
    category_b_results = []
    if request.method == 'POST':
        tournament_id = request.form.get('tournament')
        if tournament_id:
            selected_tournament = Tournament.query.get(tournament_id)
            # Fetch Category A results, ordered by points descending
            category_a_results = Point.query.filter_by(tournament_id=tournament_id, category='A')\
                .join(Player).order_by(Point.points.desc()).all()
            # Fetch Category B results, ordered by points descending
            category_b_results = Point.query.filter_by(tournament_id=tournament_id, category='B')\
                .join(Player).order_by(Point.points.desc()).all()
            return render_template(
                'view_results.html',
                tournaments=tournaments,
                selected_tournament=selected_tournament,
                category_a_results=category_a_results,
                category_b_results=category_b_results
            )
    return render_template(
        'view_results.html',
        tournaments=tournaments,
        selected_tournament=selected_tournament,
        category_a_results=category_a_results,
        category_b_results=category_b_results
    )


@app.route('/export_results/<int:tournament_id>')
@login_required
def export_results(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    points = Point.query.filter_by(tournament_id=tournament_id).join(Player).all()
    
    # Create CSV in memory
    si = io.StringIO()
    cw = csv.writer(si)
    # Write header
    cw.writerow(['First Name', 'Last Name', 'Points', 'Category'])
    # Write data
    for point in points:
        cw.writerow([point.player.first_name, point.player.last_name, point.points, point.category])
    
    output = io.BytesIO()
    output.write(si.getvalue().encode('utf-8'))
    output.seek(0)
    
    filename = f'tournament_{tournament.date}.csv'
    return send_file(output, mimetype='text/csv', as_attachment=True, download_name=filename)


@app.route('/visualization', methods=['GET', 'POST'])
@login_required
def visualization():
    form = VisualizationForm()
    
    # Populate tournaments in SelectField dynamically
    tournaments = Tournament.query.order_by(Tournament.date.desc()).all()
    form.specific_tournament.choices = [(t.id, t.date.strftime('%Y-%m-%d')) for t in tournaments]

    # Initialize variables to hold chart data
    tournament_chart_data = None
    overall_chart_data = None

    # If the form is submitted
    if form.validate_on_submit():
        visualization_type = form.visualization_type.data

        if visualization_type == 'tournament':
            # Visualization for a specific tournament
            tournament_id = form.specific_tournament.data
            top_n = form.specific_top_n.data

            # Fetch top N players for the selected tournament
            top_players_tournament = Point.query.filter_by(tournament_id=tournament_id)\
                .join(Player)\
                .order_by(Point.points.desc())\
                .limit(top_n)\
                .all()

            # Prepare labels and data for the chart
            labels_tournament = [f"{p.player.first_name} {p.player.last_name}" for p in top_players_tournament]
            data_tournament = [p.points for p in top_players_tournament]

            # Format tournament-specific chart data
            tournament_chart_data = {
                'labels': labels_tournament,
                'data': data_tournament,
                'tournament_date': Tournament.query.get(tournament_id).date.strftime('%Y-%m-%d')
            }

        elif visualization_type == 'general':
            # General classification across all tournaments or a specific year
            top_n = form.general_top_n.data
            year = form.year.data

            # Build query for general classification
            query = db.session.query(
                Player.first_name,
                Player.last_name,
                func.sum(Point.points).label('total_points')
            ).join(Point).join(Tournament)

            # Filter by year if provided
            if year:
                query = query.filter(func.strftime('%Y', Tournament.date) == str(year))

            # Finalize query with grouping and sorting
            query = query.group_by(Player.id)\
                         .order_by(func.sum(Point.points).desc())\
                         .limit(top_n)

            top_players_general = query.all()

            # Prepare labels and data for the chart
            labels_general = [f"{player.first_name} {player.last_name}" for player in top_players_general]
            data_general = [player.total_points for player in top_players_general]

            # Format general classification chart data
            overall_chart_data = {
                'labels': labels_general,
                'data': data_general,
                'description': 'Top Players Total Points Across All Tournaments'
                               if not year else f'Top Players in {year}'
            }

    # Render the visualization page with the form and chart data
    return render_template(
        'visualization.html',
        form=form,
        tournament_chart_data=tournament_chart_data,
        overall_chart_data=overall_chart_data
    )

# Initialize Database and Create Users
if __name__ == '__main__':
    # Create database tables within the application context
    with app.app_context():
        db.create_all()
        # Create users from 'users.json' if not already present
        create_users_from_file('users.json')
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
