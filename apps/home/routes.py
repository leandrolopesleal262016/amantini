# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from apps.home import blueprint
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required
from jinja2 import TemplateNotFound
from apps import db
from apps.authentication.models import Contact



@blueprint.route('/index')
@login_required
def index():
    return render_template('home/index.html', segment='index')


@blueprint.route('/contacts', methods=['GET', 'POST'])
@login_required
def contacts():
    if request.method == 'POST':
        # Manter a lógica existente de POST
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')

        new_contact = Contact(name=name, email=email, phone=phone)

        try:
            db.session.add(new_contact)
            db.session.commit()
            flash('Contato adicionado com sucesso!', 'success')
        except Exception as e:
            db.session.rollback()
            flash('Erro ao adicionar contato: ' + str(e), 'danger')

        return redirect(url_for('home_blueprint.contacts'))

    # Adicionar lógica de busca para método GET
    search = request.args.get('search', '')
    
    if search:
        # Busca por nome, email ou telefone
        contacts = Contact.query.filter(
            db.or_(
                Contact.name.ilike(f'%{search}%'),
                Contact.email.ilike(f'%{search}%'),
                Contact.phone.ilike(f'%{search}%')
            )
        ).all()
    else:
        # Se não houver busca, retorna todos os contatos
        contacts = Contact.query.all()

    return render_template('home/contacts.html', contacts=contacts, segment='contacts')


@blueprint.route('/tasks')
@login_required
def tasks():
    return render_template('home/tasks.html', segment='tasks')


@blueprint.route('/opportunities')
@login_required
def opportunities():
    return render_template('home/opportunities.html', segment='opportunities')


@blueprint.route('/reports')
@login_required
def reports():
    return render_template('home/reports.html', segment='reports')


@blueprint.route('/<template>')
@login_required
def route_template(template):
    try:
        if not template.endswith('.html'):
            template += '.html'

        # Detect the current page
        segment = get_segment(request)

        # Serve the file (if exists) from app/templates/home/FILE.html
        return render_template("home/" + template, segment=segment)

    except TemplateNotFound:
        return render_template('home/page-404.html'), 404

    except:
        return render_template('home/page-500.html'), 500
    
@blueprint.route('/contacts/edit/<int:id>', methods=['POST'])
@login_required
def edit_contact(id):
    contact = Contact.query.get(id)

    if contact:
        contact.name = request.form.get('name')
        contact.email = request.form.get('email')
        contact.phone = request.form.get('phone')

        db.session.commit()
        flash('Contato atualizado com sucesso!', 'success')
    else:
        flash('Contato não encontrado.', 'danger')

    return redirect(url_for('home_blueprint.contacts'))

@blueprint.route('/contacts/delete/<int:id>', methods=['GET'])
@login_required
def delete_contact(id):
    contact = Contact.query.get(id)
    if contact:
        db.session.delete(contact)
        db.session.commit()
        flash('Contato excluído com sucesso!', 'success')
    else:
        flash('Contato não encontrado.', 'danger')

    return redirect(url_for('home_blueprint.contacts'))

# Helper - Extract current page name from request
def get_segment(request):
    try:
        segment = request.path.split('/')[-1]

        if segment == '':
            segment = 'index'

        return segment

    except:
        return None
