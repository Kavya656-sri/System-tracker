from flask import Flask, render_template, jsonify, request, send_file
import pandas as pd
import json
import os
import sys
import io
from datetime import datetime, timedelta

app = Flask(__name__)

# Ensure UTF‑8 output
sys.stdout.reconfigure(encoding='utf-8')

DATA_FILE = os.path.join(os.path.dirname(__file__), 'activity_log.csv')

def load_data():
    df = pd.read_csv(DATA_FILE)
    # Clean column names
    df.columns = [c.strip() for c in df.columns]
    # Parse datetime columns if present
    if 'Start Time' in df.columns:
        df['Start Time'] = pd.to_datetime(df['Start Time'], errors='coerce')
    if 'End Time' in df.columns:
        df['End Time'] = pd.to_datetime(df['End Time'], errors='coerce')
    # Convert duration to seconds if not already numeric
    if 'Duration' in df.columns:
        if not pd.api.types.is_numeric_dtype(df['Duration']):
            df['Duration'] = pd.to_timedelta(df['Duration']).dt.total_seconds()
    return df# Add health endpoint
@app.route('/health')
def health():
    return jsonify({"status": "OK"})

# Update overview route to compute accurate metrics
@app.route('/')
def dashboard():
    # Dashboard Loaded
    print("Dashboard Loaded")
    df = load_data()
    print("Dataframe Exists:", 'df' in locals())
    # Normalize project names to uppercase for consistent IDLE detection
    df['Project Name'] = df['Project Name'].str.upper()
    # Total work seconds (sum of all durations)
    total_seconds = df['Duration'].sum()
    # Idle seconds: sum durations where project is IDLE
    idle_seconds = df[df['Project Name'] == 'IDLE']['Duration'].sum()
    # Productive seconds: total minus idle
    productive_seconds = total_seconds - idle_seconds
    # Debug prints (temporary)
    print('TOTAL:', total_seconds)
    print('IDLE:', idle_seconds)
    print('PRODUCTIVE:', productive_seconds)
    # Convert to hours for display
    total_work_hours = round(total_seconds / 3600, 2)
    productive_hours = round(productive_seconds / 3600, 2)
    idle_hours = round(idle_seconds / 3600, 2)
    # Productivity score
    productivity_score = round((productive_seconds / total_seconds) * 100, 2) if total_seconds else 0
    # Total sessions
    total_sessions = len(df)
    # Project breakdown
    project_counts = df.groupby('Project Name')['Duration'].sum()
    pie_labels = list(project_counts.keys())
    pie_values = [round(v / 3600, 2) for v in project_counts.values]  # hours for each category
    # Application usage (top 10)
    app_durations = df.groupby('App Name')['Duration'].sum().sort_values(ascending=False).head(10)
    bar_labels = [(lbl[:27] + '…' if len(lbl) > 27 else lbl) for lbl in app_durations.index]
    bar_full_labels = list(app_durations.index)
    bar_values = [round(v / 3600, 2) for v in app_durations.values]
    recent = df.sort_values('Start Time', ascending=False).head(10)
    recent['Start Time'] = recent['Start Time'].astype(str)
    recent_records = recent[['Project Name', 'App Name', 'Start Time', 'Duration']].to_dict(orient='records')
    return render_template('dashboard.html',
        total_sessions=total_sessions,
        productive_sessions=int(df[df['Project Name'] != 'IDLE'].shape[0]),
        idle_sessions=int(df[df['Project Name'] == 'IDLE'].shape[0]),
        productivity_score=productivity_score,
        total_work_hours=total_work_hours,
        productive_hours=productive_hours,
        idle_hours=idle_hours,
        pie_labels=json.dumps(pie_labels),
        pie_values=json.dumps(pie_values),
        bar_labels=json.dumps(bar_labels),
        bar_full_labels=json.dumps(bar_full_labels),
        bar_values=json.dumps(bar_values),
        recent_activities=json.dumps(recent_records)
    )

# ---------- Activity Log Page ----------
@app.route('/activity-log')
def activity_log_page():
    # Render page – data will be loaded via AJAX
    return render_template('activity_log.html')
# Alias route for sidebar navigation
@app.route('/overview')
def overview():
    return dashboard()

# Helper function to filter dataframe based on request arguments
def filter_dataframe(df, args):
    """Apply search, project, and date filters to the dataframe based on request args."""
    # Search term
    search = args.get('search[value]', '').strip().lower()
    if search:
        mask = (
            df['Project Name'].astype(str).str.lower().str.contains(search) |
            df['App Name'].astype(str).str.lower().str.contains(search) |
            df.get('Window Title', pd.Series([''])).astype(str).str.lower().str.contains(search) |
            df.apply(lambda row: ' '.join(row.astype(str)), axis=1).str.lower().str.contains(search)
        )
        df = df[mask]
    # Project filter
    project = args.get('project')
    if project and project != 'All':
        df = df[df['Project Name'] == project]
    # Date filter
    date_filter = args.get('date_filter')
    if date_filter:
        today = datetime.now().date()
        if date_filter == 'today':
            df = df[df['Start Time'].dt.date == today]
        elif date_filter == 'last7':
            df = df[df['Start Time'] >= today - timedelta(days=7)]
        elif date_filter == 'last30':
            df = df[df['Start Time'] >= today - timedelta(days=30)]
        elif date_filter == 'custom':
            start_str = args.get('date_start')
            end_str = args.get('date_end')
            if start_str and end_str:
                start_dt = pd.to_datetime(start_str)
                end_dt = pd.to_datetime(end_str)
                df = df[(df['Start Time'] >= start_dt) & (df['Start Time'] <= end_dt)]
    return df

@app.route('/api/activity-data')
def activity_data():
    df = load_data()
    # Normalize project names to uppercase
    df['Project Name'] = df['Project Name'].str.upper()
    # Summary stats (total before filtering)
    total_records = len(df)
    total_work_time = df['Duration'].sum()
    idle_time = df[df['Project Name'] == 'IDLE']['Duration'].sum()
    productive_time = total_work_time - idle_time
    # Debug prints (temporary)
    print('ACTIVITY TOTAL:', total_work_time)
    print('ACTIVITY IDLE:', idle_time)
    print('ACTIVITY PRODUCTIVE:', productive_time)

    # Apply filtering & searching
    filtered_df = filter_dataframe(df, request.args)
    records_filtered = len(filtered_df)

    # Sorting
    order_col_index = request.args.get('order[0][column]')
    order_dir = request.args.get('order[0][dir]', 'asc')
    columns = ['Project Name', 'App Name', 'Start Time', 'End Time', 'Duration']
    if order_col_index is not None and order_col_index.isdigit():
        col_name = columns[int(order_col_index)]
        filtered_df = filtered_df.sort_values(col_name, ascending=(order_dir == 'asc'))

    # Pagination
    start = int(request.args.get('start', 0))
    length = int(request.args.get('length', 10))
    page_df = filtered_df.iloc[start:start+length]

    # Convert datetime columns to string for JSON serialization
    df_page = page_df[columns].copy()
    for col in ['Start Time', 'End Time']:
        if col in df_page.columns:
            df_page[col] = df_page[col].astype(str)
    data = df_page.fillna('').to_dict(orient='records')

    return jsonify({
        'draw': int(request.args.get('draw', 1)),
        'recordsTotal': total_records,
        'recordsFiltered': records_filtered,
        'data': data,
        'summary': {
            'total_records': total_records,
            'total_work_time': total_work_time,
            'productive_time': productive_time,
            'idle_time': idle_time
        }
    })

@app.route('/export/activity')
def export_activity():
    df = load_data()
    filtered_df = filter_dataframe(df, request.args)
    fmt = request.args.get('format', 'csv')
    if fmt == 'excel':
        # Requires openpyxl – ensure it's installed
        output = io.BytesIO()
        filtered_df.to_excel(output, index=False, engine='openpyxl')
        output.seek(0)
        return send_file(output, as_attachment=True,
                         download_name='activity_log.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    else:
        csv_data = filtered_df.to_csv(index=False)
        return send_file(io.BytesIO(csv_data.encode('utf-8')),
                         as_attachment=True,
                         download_name='activity_log.csv',
                         mimetype='text/csv')

# Productivity page route – renders dashboard with page flag
@app.route('/productivity')
def productivity():
    # Render dashboard template with page identifier for conditional rendering
    return render_template('dashboard.html', page='productivity')

# API endpoint for productivity data aggregation
@app.route('/api/productivity')
def api_productivity():
    df = load_data()
    # Normalize project names to uppercase
    df['Project Name'] = df['Project Name'].str.upper()
    # Summary calculations (seconds -> hours)
    total_work_seconds = df['Duration'].sum()
    idle_seconds = df[df['Project Name'] == 'IDLE']['Duration'].sum()
    productive_seconds = total_work_seconds - idle_seconds
    # Debug prints (to be removed after verification)
    print('Total seconds:', total_work_seconds)
    print('Idle seconds:', idle_seconds)
    print('Productive seconds:', productive_seconds)
    total_work_hours = round(total_work_seconds / 3600, 2)
    productive_hours = round(productive_seconds / 3600, 2)
    idle_hours = round(idle_seconds / 3600, 2)
    productivity_score = round((productive_seconds / total_work_seconds) * 100, 2) if total_work_seconds else 0
    # Project breakdown
    proj_group = df.groupby('Project Name')['Duration'].sum().reset_index()
    proj_group['Hours'] = proj_group['Duration'] / 3600
    proj_group['Percentage'] = round(proj_group['Hours'] / total_work_hours * 100, 2) if total_work_hours else 0
    proj_data = proj_group[['Project Name', 'Hours', 'Percentage']].to_dict(orient='records')
    # Top applications
    app_group = df.groupby('App Name')['Duration'].sum().reset_index()
    app_group = app_group.sort_values('Duration', ascending=False).head(10)
    app_group['Hours'] = app_group['Duration'] / 3600
    app_group['Percentage'] = round(app_group['Hours'] / total_work_hours * 100, 2) if total_work_hours else 0
    app_data = app_group[['App Name', 'Hours', 'Percentage']].to_dict(orient='records')
    # Productivity trend (daily productive hours)
    df['Date'] = df['Start Time'].dt.date
    daily = df[df['Duration'] > 0].groupby('Date')['Duration'].sum().reset_index()
    daily['Hours'] = daily['Duration'] / 3600
    trend_data = daily[['Date', 'Hours']].to_dict(orient='records')
    return jsonify({
        'summary': {
            'productivity_score': productivity_score,
            'total_work_hours': total_work_hours,
            'productive_hours': productive_hours,
            'idle_hours': idle_hours
        },
        'project_breakdown': proj_data,
        'top_apps': app_data,
        'trend': trend_data
    })

def get_current_report_data():
    df = load_data()
    total_sessions = len(df)
    productive_categories = ["Development", "Browser Work", "Google Chrome", "Microsoft Edge", "Office Work", "Communication"]
    productive_sessions = len(df[df['Project Name'].isin(productive_categories)]) if not df.empty else 0
    entertainment_sessions = len(df[df['Project Name'] == 'Entertainment']) if not df.empty else 0
    idle_sessions = len(df[df['Project Name'] == 'IDLE']) if not df.empty else 0
    if total_sessions > 0:
        productivity_score = round((productive_sessions / total_sessions) * 100, 2)
    else:
        productivity_score = 0.0
        
    return {
        "summary": {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "total_sessions": total_sessions,
            "productive_sessions": productive_sessions,
            "entertainment_sessions": entertainment_sessions,
            "idle_sessions": idle_sessions,
            "productivity_score": productivity_score
        }
    }

@app.route('/email-verification')
@app.route('/email_verification')
def email_verification():
    return render_template('email_verification.html')

@app.route('/api/email-data')
def api_email_data():
    df = load_data()
    
    total_apps = int(df['App Name'].nunique()) if not df.empty else 0
    total_projects = int(df['Project Name'].nunique()) if not df.empty else 0
    total_work_seconds = float(df['Duration'].sum()) if not df.empty else 0
    
    hours = int(total_work_seconds // 3600)
    minutes = int((total_work_seconds % 3600) // 60)
    seconds = int(total_work_seconds % 60)
    total_work_duration = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    
    # Read email status
    status_file = 'email_status.json'
    if os.path.exists(status_file):
        try:
            with open(status_file, 'r') as sf:
                last_status_data = json.load(sf)
        except Exception:
            last_status_data = {
                "last_status": "never",
                "last_run": "Never",
                "error_message": None
            }
    else:
        last_status_data = {
            "last_status": "never",
            "last_run": "Never",
            "error_message": None
        }

    from email_sender import generate_timesheet
    timesheet_report = generate_timesheet()
    
    # Parse timesheet_report to extract WORK TIMESHEET and SYSTEM ACTIVITY
    work_timesheet = []
    system_activity = []
    
    current_section = None
    for line in timesheet_report.splitlines():
        line = line.strip()
        if not line or line.startswith('='):
            continue
        if line == 'WORK TIMESHEET':
            current_section = 'work'
            continue
        if line == 'SYSTEM ACTIVITY':
            current_section = 'system'
            continue
            
        parts = line.split('\t')
        if len(parts) >= 2:
            row = {'Application Name': parts[0].strip(), 'Duration': parts[1].strip()}
            if current_section == 'work':
                work_timesheet.append(row)
            elif current_section == 'system':
                system_activity.append(row)

    return jsonify({
        "summary": {
            "total_applications": total_apps,
            "total_projects": total_projects,
            "total_work_duration": total_work_duration,
            "last_status": last_status_data.get("last_status", "never"),
            "last_run": last_status_data.get("last_run", "Never"),
            "error_message": last_status_data.get("error_message")
        },
        "work_timesheet": work_timesheet,
        "system_activity": system_activity
    })

@app.route('/api/email-content')
def api_email_content():
    """Return the auto-generated subject and body so the frontend can load them into the editor."""
    try:
        from email_sender import build_email_body, get_today_date
        subject = f"Daily Productivity Report - {get_today_date()}"
        body = build_email_body()
        return jsonify({"success": True, "subject": subject, "body": body})
    except Exception as e:
        print("EMAIL CONTENT ERROR:", str(e))
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/send-email', methods=['POST'])
def trigger_send_email():
    print("================ DEBUG INFO ================")
    print("CWD:", os.getcwd())
    print("activity_log.csv exists:", os.path.exists("activity_log.csv"))
    print("============================================")

    try:
        # Accept JSON or form data
        data = request.get_json(silent=True) or {}
        custom_subject = data.get('subject') or request.form.get('subject')
        custom_body    = data.get('body')    or request.form.get('body')

        from email_sender import send_email
        success = send_email(subject=custom_subject, body=custom_body)
        if success:
            return jsonify({"success": True, "message": "Email Sent Successfully"})
        else:
            error_message = "Unknown error occurred"
            if os.path.exists("email_status.json"):
                try:
                    with open("email_status.json", "r") as sf:
                        status_data = json.load(sf)
                        error_message = status_data.get("error_message") or error_message
                except Exception:
                    pass
            return jsonify({"success": False, "error_message": error_message})
    except Exception as e:
        print("EMAIL ERROR:", str(e))
        return jsonify({"success": False, "error_message": str(e)})


@app.route('/application_usage')
@app.route('/application-usage')
def application_usage():
    return render_template('application_usage.html')

@app.route('/api/application-usage')
def api_application_usage():
    try:
        # 1. Read application_work_duration.csv for total durations
        duration_file = os.path.join(os.path.dirname(__file__), 'application_work_duration.csv')
        if not os.path.exists(duration_file):
            return jsonify({'error': 'application_work_duration.csv not found'})
            
        dur_df = pd.read_csv(duration_file)
        
        # 2. Data Cleaning & Grouping Helper
        def clean_app_name(raw_name):
            if not isinstance(raw_name, str): return "Unknown"
            name = raw_name.replace('•', '').replace('●', '').strip()
            
            name_lower = name.lower()
            if 'antigravity ide' in name_lower: return 'Antigravity IDE'
            if 'google chrome' in name_lower or 'chrome' in name_lower: return 'Google Chrome'
            if 'visual studio code' in name_lower or 'vs code' in name_lower: return 'Visual Studio Code'
            if 'whatsapp' in name_lower: return 'WhatsApp'
            if 'microsoft edge' in name_lower or 'edge' in name_lower: return 'Microsoft Edge'
            if 'system idle' in name_lower: return 'System Idle'
            if 'file explorer' in name_lower: return 'File Explorer'
            
            # Remove any specific tabs/titles by splitting if it matches format "Title - App"
            parts = name.split(' - ')
            return parts[-1].strip() if len(parts) > 1 else name.strip()

        # Parse Timedelta strings to seconds
        dur_df['Duration_Sec'] = pd.to_timedelta(dur_df['Total Time Worked']).dt.total_seconds()
        dur_df['Clean_App'] = dur_df['Application Name'].apply(clean_app_name)
        
        # Group durations by cleaned app name
        app_durations = dur_df.groupby('Clean_App')['Duration_Sec'].sum().reset_index()
        app_durations = app_durations.sort_values(by='Duration_Sec', ascending=False)
        
        total_time_secs = app_durations['Duration_Sec'].sum()
        
        def fmt_seconds(s):
            h = int(s // 3600); m = int((s % 3600) // 60); sec = int(s % 60)
            return f"{h:02d}:{m:02d}:{sec:02d}"

        # 3. Read activity_log.csv for session insights (Avg Session, Longest Session)
        act_df = load_data()
        total_sessions = len(act_df)
        avg_session_secs = act_df['Duration'].mean() if total_sessions > 0 else 0
        longest_session_secs = act_df['Duration'].max() if total_sessions > 0 else 0
        
        # Format the top applications
        top_apps = []
        app_table_data = []
        for idx, row in app_durations.iterrows():
            pct = round((row['Duration_Sec'] / total_time_secs) * 100, 2) if total_time_secs else 0
            
            cat = "Development" if row['Clean_App'] in ["Visual Studio Code", "Antigravity IDE"] else "Google Chrome" if row['Clean_App'] == "Google Chrome" else "Microsoft Edge" if row['Clean_App'] == "Microsoft Edge" else "Communication" if row['Clean_App'] == "WhatsApp" else "Other"
            
            app_table_data.append({
                'Application Name': row['Clean_App'],
                'Total Duration': fmt_seconds(row['Duration_Sec']),
                'Percentage': pct,
                'Category': cat
            })
            
            top_apps.append({
                'name': row['Clean_App'],
                'duration': fmt_seconds(row['Duration_Sec']),
                'seconds': row['Duration_Sec']
            })

        most_used_app = top_apps[0]['name'] if top_apps else "N/A"
        least_used_app = top_apps[-1]['name'] if top_apps else "N/A"
        
        # Prepare Doughnut chart data (Specific apps + Other)
        doughnut_apps = ["Antigravity IDE", "Visual Studio Code", "Google Chrome", "WhatsApp"]
        doughnut_data = {app: 0 for app in doughnut_apps}
        doughnut_data["Other"] = 0
        
        for idx, row in app_durations.iterrows():
            if row['Clean_App'] in doughnut_apps:
                doughnut_data[row['Clean_App']] += row['Duration_Sec']
            else:
                doughnut_data["Other"] += row['Duration_Sec']
                
        # Calculate percentages for doughnut
        doughnut_pcts = []
        for app in doughnut_apps + ["Other"]:
            pct = round((doughnut_data[app] / total_time_secs) * 100, 2) if total_time_secs else 0
            doughnut_pcts.append({'name': app, 'percentage': pct})

        return jsonify({
            'summary': {
                'total_applications': len(app_durations),
                'total_usage_time': fmt_seconds(total_time_secs),
                'most_used_application': most_used_app,
                'average_session_duration': fmt_seconds(avg_session_secs)
            },
            'insights': {
                'most_used_application': most_used_app,
                'least_used_application': least_used_app,
                'longest_recorded_session': fmt_seconds(longest_session_secs),
                'total_tracked_time': fmt_seconds(total_time_secs)
            },
            'top_apps': top_apps[:10],
            'doughnut_data': doughnut_pcts,
            'app_table': app_table_data
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/reports')
def reports():
    return render_template('reports.html')

@app.route('/download/excel')
def download_excel():
    path = os.path.join(os.path.dirname(__file__), 'daily_report.xlsx')
    if not os.path.exists(path):
        try:
            import report_generator
            report_generator.generate_report()
        except:
            pass
    if os.path.exists(path):
        return send_file(path, as_attachment=True, download_name='daily_report.xlsx')
    return "Excel report file not found. Please generate a report first.", 404

@app.route('/download/text')
def download_text():
    path = os.path.join(os.path.dirname(__file__), 'daily_report.txt')
    if not os.path.exists(path):
        try:
            import report_generator
            report_generator.generate_report()
        except:
            pass
    if os.path.exists(path):
        return send_file(path, as_attachment=True, download_name='daily_report.txt')
    return "Text report file not found. Please generate a report first.", 404

@app.route('/download/activity-log')
def download_activity_log():
    path = os.path.join(os.path.dirname(__file__), 'activity_log.csv')
    if os.path.exists(path):
        return send_file(path, as_attachment=True, download_name='activity_log.csv')
    return "Activity log CSV not found.", 404

@app.route('/download/app-usage')
def download_app_usage():
    path = os.path.join(os.path.dirname(__file__), 'application_work_duration.csv')
    if os.path.exists(path):
        return send_file(path, as_attachment=True, download_name='application_work_duration.csv')
    return "Application work duration CSV not found.", 404

@app.route('/api/generate-report', methods=['POST'])
def api_generate_report():
    try:
        import report_generator
        import shutil
        
        report_data = report_generator.generate_report()
        if not report_data:
            return jsonify({'error': 'Report generation failed. Is the activity log empty?'}), 400
        
        txt_src = report_data.get('text_report')
        xlsx_src = report_data.get('excel_report')
        
        if txt_src and os.path.exists(txt_src):
            shutil.copy(txt_src, os.path.join(os.path.dirname(__file__), 'daily_report.txt'))
        if xlsx_src and os.path.exists(xlsx_src):
            shutil.copy(xlsx_src, os.path.join(os.path.dirname(__file__), 'daily_report.xlsx'))
            
        return jsonify({
            'success': True,
            'message': 'Report Generated Successfully',
            'summary': report_data.get('summary')
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/reports-list')
def api_reports_list():
    try:
        reports_dir = os.path.join(os.path.dirname(__file__), 'reports')
        if not os.path.exists(reports_dir):
            os.makedirs(reports_dir, exist_ok=True)
            
        files = os.listdir(reports_dir)
        reports_list = []
        
        for f in files:
            if f.startswith('daily_report_') and (f.endswith('.txt') or f.endswith('.xlsx')):
                file_path = os.path.join(reports_dir, f)
                stat = os.stat(file_path)
                size_bytes = stat.st_size
                mtime = stat.st_mtime
                gen_time = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
                
                parts = f.split('_')
                date_part = 'N/A'
                if len(parts) >= 3:
                    date_part = parts[2].split('.')[0]
                    
                file_type = "Excel Document" if f.endswith('.xlsx') else "Text Report"
                
                reports_list.append({
                    'filename': f,
                    'path': file_path,
                    'date': date_part,
                    'gen_time': gen_time,
                    'type': file_type,
                    'size': f"{size_bytes / 1024:.2f} KB" if size_bytes >= 1024 else f"{size_bytes} B",
                    'raw_size': size_bytes,
                    'raw_mtime': mtime
                })
                
        reports_list.sort(key=lambda x: x['raw_mtime'], reverse=True)
        
        latest_preview = "No report generated yet."
        latest_report_name = "N/A"
        latest_report_date = "N/A"
        latest_report_size = "N/A"
        latest_report_type = "N/A"
        
        txt_files = [r for r in reports_list if r['filename'].endswith('.txt')]
        if txt_files:
            latest_txt = txt_files[0]
            latest_report_name = latest_txt['filename']
            latest_report_date = latest_txt['date']
            latest_report_size = latest_txt['size']
            latest_report_type = "Text Report"
            try:
                with open(latest_txt['path'], 'r', encoding='utf-8') as file:
                    lines = [file.readline() for _ in range(30)]
                    latest_preview = "".join(lines)
            except Exception as err:
                latest_preview = f"Error reading preview: {str(err)}"
        elif reports_list:
            latest = reports_list[0]
            latest_report_name = latest['filename']
            latest_report_date = latest['date']
            latest_report_size = latest['size']
            latest_report_type = latest['type']
            
        excel_preview = []
        xlsx_files = [r for r in reports_list if r['filename'].endswith('.xlsx')]
        if xlsx_files:
            try:
                df = pd.read_excel(xlsx_files[0]['path'])
                df.columns = [c.strip() for c in df.columns]
                preview_cols = ['Project Name', 'App Name', 'Start Time', 'Duration']
                preview_cols = [c for c in preview_cols if c in df.columns]
                df_preview = df[preview_cols].head(10).copy()
                for col in df_preview.columns:
                    if 'Time' in col:
                        df_preview[col] = df_preview[col].astype(str)
                excel_preview = df_preview.fillna('').to_dict(orient='records')
            except Exception as e:
                print("Excel preview error:", str(e))
                
        unique_dates = len(set(r['date'] for r in reports_list))
        last_gen_time = reports_list[0]['gen_time'] if reports_list else 'N/A'
        
        return jsonify({
            'reports': reports_list,
            'stats': {
                'total_reports': len(reports_list),
                'unique_days': unique_dates,
                'last_generated_time': last_gen_time,
                'status': 'Active' if reports_list else 'No Reports'
            },
            'latest': {
                'filename': latest_report_name,
                'date': latest_report_date,
                'size': latest_report_size,
                'type': latest_report_type,
                'text_preview': latest_preview,
                'excel_preview': excel_preview
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/reports-data')
def api_reports_data():
    df = load_data()
    if df.empty:
        return jsonify({'error': 'No data found'})

    def fmt(s):
        h = int(s // 3600); m = int((s % 3600) // 60); sec = int(s % 60)
        return f"{h:02d}:{m:02d}:{sec:02d}"

    productive_cats = ['Development', 'Browser Work', 'Google Chrome', 'Microsoft Edge', 'Office Work', 'Communication']
    total_sessions = len(df)
    productive_sessions = len(df[df['Project Name'].isin(productive_cats)])
    idle_sessions = len(df[df['Project Name'] == 'IDLE'])
    total_secs = float(df['Duration'].sum())
    prod_secs = float(df[df['Project Name'].isin(productive_cats)]['Duration'].sum())
    idle_secs = float(df[df['Project Name'] == 'IDLE']['Duration'].sum())
    score = round((productive_sessions / total_sessions) * 100, 2) if total_sessions else 0

    # Daily productivity
    df['Date'] = df['Start Time'].dt.date.astype(str)
    daily = df.groupby('Date').agg(
        total_seconds=('Duration', 'sum'),
        session_count=('App Name', 'count')
    ).reset_index()
    daily_report = [{'date': str(r['Date']), 'hours': round(float(r['total_seconds']) / 3600, 2), 'sessions': int(r['session_count'])} for _, r in daily.iterrows()]

    # Project summary
    proj_group = df.groupby('Project Name').agg(
        total_seconds=('Duration', 'sum'),
        session_count=('App Name', 'count')
    ).reset_index().sort_values('total_seconds', ascending=False)
    project_report = [{
        'project': r['Project Name'],
        'duration': fmt(r['total_seconds']),
        'seconds': float(r['total_seconds']),
        'sessions': int(r['session_count']),
        'percentage': round((float(r['total_seconds']) / total_secs) * 100, 2) if total_secs else 0
    } for _, r in proj_group.iterrows()]

    # Top apps summary
    app_group = df.groupby('App Name')['Duration'].sum().reset_index().sort_values('Duration', ascending=False).head(15)
    app_report = [{
        'app': r['App Name'],
        'duration': fmt(r['Duration']),
        'seconds': float(r['Duration']),
        'percentage': round((float(r['Duration']) / total_secs) * 100, 2) if total_secs else 0
    } for _, r in app_group.iterrows()]

    return jsonify({
        'summary': {
            'total_sessions': total_sessions,
            'productive_sessions': productive_sessions,
            'idle_sessions': idle_sessions,
            'total_duration': fmt(total_secs),
            'productive_duration': fmt(prod_secs),
            'idle_duration': fmt(idle_secs),
            'productivity_score': score,
            'date_range': {'start': daily_report[0]['date'] if daily_report else 'N/A', 'end': daily_report[-1]['date'] if daily_report else 'N/A'}
        },
        'daily': daily_report,
        'projects': project_report,
        'apps': app_report
    })
if __name__ == '__main__':
    app.run(debug=True, port=5000, host='0.0.0.0')
