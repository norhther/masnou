# app.py

from flask import Flask, render_template, request, redirect, url_for, send_file, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from sqlalchemy import UniqueConstraint, func
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, FloatField, SubmitField, DateField, RadioField, IntegerField, BooleanField
from wtforms.validators import DataRequired, NumberRange, ValidationError, Optional
import unicodedata
import csv
import io
import os
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key_here'  # Replace with a strong secret key
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chess_tournament.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

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

# Database Models
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

# Forms
class PlayerForm(FlaskForm):
    first_name = StringField('First Name', validators=[DataRequired()])
    last_name = StringField('Last Name', validators=[DataRequired()])
    submit = SubmitField('Add Player')

class TournamentForm(FlaskForm):
    date = DateField('Date', validators=[DataRequired()])
    submit = SubmitField('Add Tournament')

class EditTournamentForm(FlaskForm):
    date = DateField('Date', validators=[DataRequired()])
    submit = SubmitField('Update Tournament')

class PointForm(FlaskForm):
    tournament = SelectField('Tournament', coerce=int, validators=[DataRequired()])
    player = SelectField('Player', coerce=int, validators=[DataRequired()])
    points = FloatField(
        'Points',
        validators=[
            DataRequired(),
            NumberRange(min=0),
            HalfStepCheck  # Custom validator added here
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

# Utility Functions
def normalize_name(name):
    # Remove diacritics and special characters
    name = unicodedata.normalize('NFD', name)
    name = ''.join([c for c in name if unicodedata.category(c) != 'Mn'])
    # Remove non-alphabetic characters
    name = ''.join(filter(str.isalpha, name))
    # Capitalize first letter
    return name.capitalize()

# Routes
@app.route('/')
def index():
    return render_template('base.html')

@app.route('/add_player', methods=['GET', 'POST'])
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
def edit_tournament(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    form = EditTournamentForm(obj=tournament)
    if form.validate_on_submit():
        tournament.date = form.date.data
        try:
            db.session.commit()
            flash('Tournament updated successfully.', 'success')
            return redirect(url_for('view_tournaments'))
        except IntegrityError:
            db.session.rollback()
            flash('Error updating tournament. The tournament date must be unique.', 'danger')
    elif request.method == 'POST':
        flash('Please correct the errors in the form.', 'danger')
    return render_template('edit_tournament.html', form=form, tournament=tournament)

@app.route('/delete_tournament/<int:tournament_id>', methods=['POST'])
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

@app.route('/view_tournaments')
def view_tournaments():
    tournaments = Tournament.query.order_by(Tournament.date.desc()).all()
    return render_template('view_tournaments.html', tournaments=tournaments)

@app.route('/add_points', methods=['GET', 'POST'])
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
def visualization():
    form = VisualizationForm()
    tournaments = Tournament.query.order_by(Tournament.date.desc()).all()
    form.specific_tournament.choices = [(t.id, t.date.strftime('%Y-%m-%d')) for t in tournaments]
    
    if request.method == 'GET':
        latest_tournament = Tournament.query.order_by(Tournament.date.desc()).first()
        if latest_tournament and latest_tournament.date:
            form.year.data = latest_tournament.date.year

    tournament_chart_data = None
    overall_chart_data = None
    
    if form.validate_on_submit():
        visualization_type = form.visualization_type.data
        
        if visualization_type == 'tournament':
            # Specific Tournament Visualization
            tournament_id = form.specific_tournament.data
            top_n = form.specific_top_n.data
            
            top_players_tournament = Point.query.filter_by(tournament_id=tournament_id)\
                .join(Player)\
                .order_by(Point.points.desc())\
                .limit(top_n)\
                .all()
            
            labels_tournament = [f"{point.player.first_name} {point.player.last_name}" for point in top_players_tournament]
            data_tournament = [point.points for point in top_players_tournament]
            
            tournament_chart_data = {
                'labels': labels_tournament,
                'data': data_tournament,
                'tournament_date': Tournament.query.get(tournament_id).date.strftime('%Y-%m-%d')
            }
        
        elif visualization_type == 'general':
            # General Classification Visualization
            top_n = form.general_top_n.data
            year = form.year.data
            
            query = db.session.query(
                Player.first_name,
                Player.last_name,
                db.func.sum(Point.points).label('total_points')
            ).join(Point).join(Tournament)
            
            if year:
                query = query.filter(db.extract('year', Tournament.date) == year)
            
            query = query.group_by(Player.id)\
                         .order_by(db.func.sum(Point.points).desc())\
                         .limit(top_n)
            
            top_players = query.all()
            
            labels = [f"{player.first_name} {player.last_name}" for player in top_players]
            data = [player.total_points for player in top_players]
            
            overall_chart_data = {
                'labels': labels,
                'data': data,
                'description': 'Top Players Total Points Across All Tournaments'
            }
    
    
    return render_template('visualization.html', form=form, 
                           tournament_chart_data=tournament_chart_data, 
                           overall_chart_data=overall_chart_data)



# Initialize Database
if __name__ == '__main__':
    # Create database tables within the application context
    with app.app_context():
        db.create_all()
    app.run(debug=True)
