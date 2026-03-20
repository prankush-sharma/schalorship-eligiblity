import os
import io
import traceback
from functools import wraps
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from PIL import Image
import imagehash
import numpy as np
import cv2
import fitz  # PyMuPDF

# Check if OpenCV QR detector is available
try:
    _qr_detector = cv2.QRCodeDetector()
    QR_AVAILABLE = True
except Exception:
    QR_AVAILABLE = False

from models import init_db, add_scorecard, check_duplicate, get_all_scorecards, delete_scorecard, get_scorecard_count

app = Flask(__name__)
# Ensure database schema is initialized on startup (even in Gunicorn)
init_db()

app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max upload
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'bmp', 'gif', 'tiff', 'webp', 'pdf'}
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'goadmin2025')

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        from flask import request
        auth_header = request.headers.get('Authorization')
        if not auth_header or auth_header != f"Bearer {ADMIN_PASSWORD}":
            return jsonify({'error': 'Unauthorized authentication', 'status': 'error'}), 401
        return f(*args, **kwargs)
    return decorated


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_qr_data(image):
    """Extract QR code data from a PIL image using OpenCV."""
    if not QR_AVAILABLE:
        return None

    try:
        # Convert PIL Image to OpenCV format (numpy array)
        img_array = np.array(image.convert('RGB'))
        # OpenCV uses BGR, PIL uses RGB
        img_cv = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)

        # Detect and decode QR codes
        data, points, _ = _qr_detector.detectAndDecode(img_cv)

        if data and len(data) > 0 and data != '':
            return data

        # Try with grayscale for better detection
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        data, points, _ = _qr_detector.detectAndDecode(gray)

        if data and len(data) > 0 and data != '':
            return data

    except Exception as e:
        print(f"QR decode error: {e}")
    return None


def compute_image_hash(image):
    """Compute perceptual hash of the image."""
    try:
        phash = imagehash.phash(image)
        return str(phash)
    except Exception as e:
        print(f"Image hash error: {e}")
        return None


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/upload', methods=['POST'])
def upload_scorecard():
    """Upload a score card and check for duplicates."""
    try:
        # Validate file
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded', 'status': 'error'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected', 'status': 'error'}), 400

        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type. Please upload an image or PDF', 'status': 'error'}), 400

        # Get student name
        student_name = request.form.get('student_name', '').strip()
        if not student_name:
            return jsonify({'error': 'Student name is required', 'status': 'error'}), 400

        registration_no = request.form.get('registration_no', '').strip()
        gate_score = request.form.get('gate_score', '').strip()
        branch = request.form.get('branch', '').strip()
        rank_str = request.form.get('rank', '').strip()
        try:
            rank = int(rank_str) if rank_str else None
        except ValueError:
            rank = None

        # Eligibility Check
        allowed_branches = [
            "cs", "computer science", "computer science and information technology", 
            "computer science and engineering", "da", "data science and artificial intelligence",
            "data science & artificial intelligence"
        ]
        if not branch or branch.lower() not in allowed_branches:
            return jsonify({
                'status': 'rejected',
                'message': f'Not eligible for scholarship. Branch "{branch}" is not eligible. Only CS and DA are allowed.'
            }), 200

        if rank is None or rank > 500:
            return jsonify({
                'status': 'rejected',
                'message': f'Not eligible for scholarship. Rank must be 500 or below. (Found Rank: {rank})'
            }), 200

        # Read and process image
        image_bytes = file.read()
        
        if file.filename.lower().endswith('.pdf'):
            try:
                pdf_document = fitz.open(stream=image_bytes, filetype="pdf")
                if len(pdf_document) == 0:
                    return jsonify({'error': 'PDF is empty', 'status': 'error'}), 400
                page = pdf_document.load_page(0)
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # upscale for better QR reading
                image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                pdf_document.close()
            except Exception as e:
                return jsonify({'error': f'Invalid PDF file: {e}', 'status': 'error'}), 400
        else:
            image = Image.open(io.BytesIO(image_bytes))

        # Extract QR code data
        qr_data = extract_qr_data(image)

        import re
        import json
        
        # Security: Cross-verify Form Data against genuine QR Code data
        if qr_data:
            qr_reg = None
            qr_score = None
            qr_rank = None
            
            try:
                qr_obj = json.loads(qr_data)
                qr_reg = qr_obj.get("reg") or qr_obj.get("registration") or qr_obj.get("registration_no")
                qr_score = qr_obj.get("score") or qr_obj.get("gate_score")
                qr_rank = qr_obj.get("rank") or qr_obj.get("air")
            except Exception:
                pass
                
            if not qr_reg:
                match = re.search(r'\b([A-Z]{2}\d{2}[A-Z0-9]{5,10})\b', qr_data, re.IGNORECASE)
                if match: qr_reg = match.group(1).upper()
            if not qr_score:
                match = re.search(r'(?:score|marks)[\s:="\']*(\d{2,4})', qr_data, re.IGNORECASE)
                if match: qr_score = match.group(1)
            if not qr_rank:
                match = re.search(r'(?:rank|air|all india rank)[\s:="\']*(\d{1,5})', qr_data, re.IGNORECASE)
                if match: qr_rank = match.group(1)
            
            if qr_reg and registration_no and qr_reg.upper() != registration_no.upper():
                return jsonify({'status': 'rejected', 'message': 'FRAUD DETECTED: Form Registration No. does not match the original GATE QR Code.'}), 200
            if qr_score and gate_score and str(qr_score) != str(gate_score):
                return jsonify({'status': 'rejected', 'message': 'FRAUD DETECTED: Form GATE Score does not match the original GATE QR Code.'}), 200
            if qr_rank and rank and str(qr_rank) != str(rank):
                return jsonify({'status': 'rejected', 'message': 'FRAUD DETECTED: Form Rank does not match the original GATE QR Code.'}), 200

        # Compute perceptual hash
        image_hash = compute_image_hash(image)

        # Check for duplicates
        duplicate = check_duplicate(qr_data, image_hash)

        if duplicate:
            return jsonify({
                'status': 'duplicate',
                'message': 'DUPLICATE DETECTED! This score card has already been used for a scholarship.',
                'existing_record': {
                    'student_name': duplicate['student_name'],
                    'registration_no': duplicate['registration_no'] or 'N/A',
                    'gate_score': duplicate['gate_score'] or 'N/A',
                    'branch': duplicate['branch'] or 'N/A',
                    'rank': duplicate['rank'] or 'N/A',
                    'uploaded_at': duplicate['uploaded_at'],
                    'original_filename': duplicate['original_filename']
                },
                'match_type': 'QR Code' if (qr_data and duplicate.get('qr_data') == qr_data) else 'Image Hash'
            }), 200

        # No duplicate — save the record
        # Save file to disk
        safe_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
        filepath = os.path.join(UPLOAD_FOLDER, safe_filename)
        with open(filepath, 'wb') as f:
            f.write(image_bytes)

        record_id = add_scorecard(
            student_name=student_name,
            registration_no=registration_no,
            qr_data=qr_data,
            image_hash=image_hash,
            gate_score=gate_score,
            branch=branch,
            rank=rank,
            original_filename=file.filename
        )

        return jsonify({
            'status': 'approved',
            'message': 'Scholarship APPROVED! This score card is verified and unique.',
            'record': {
                'id': record_id,
                'student_name': student_name,
                'registration_no': registration_no,
                'gate_score': gate_score,
                'branch': branch,
                'rank': rank,
                'qr_data_found': qr_data is not None,
                'image_hash': image_hash
            }
        }), 201

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e), 'status': 'error'}), 500


@app.route('/api/extract', methods=['POST'])
def extract_text():
    """Extract text from PDF and scan QR code for auto-fill."""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded', 'status': 'error'}), 400
            
        file = request.files['file']
        text = ""
        qr_data = None
        image_bytes = file.read()
        
        if file.filename.lower().endswith('.pdf'):
            try:
                pdf_document = fitz.open(stream=image_bytes, filetype="pdf")
                # Only extract text from up to first 3 pages
                for page_num in range(min(3, len(pdf_document))):
                    text += pdf_document.load_page(page_num).get_text() + "\n"
                    
                # Scrape QR Code from the first page if available
                if QR_AVAILABLE and len(pdf_document) > 0:
                    pix = pdf_document.load_page(0).get_pixmap(matrix=fitz.Matrix(2, 2))
                    qr_img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    qr_data = extract_qr_data(qr_img)

                pdf_document.close()
            except Exception as e:
                pass # gracefully continue if PDF is somehow mangled
        else:
            try:
                if QR_AVAILABLE:
                    qr_img = Image.open(io.BytesIO(image_bytes))
                    qr_data = extract_qr_data(qr_img)
            except Exception as e:
                pass

        return jsonify({'status': 'success', 'text': text, 'qr_data': qr_data})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e), 'status': 'error'}), 500


@app.route('/api/scorecards', methods=['GET'])
@require_auth
def list_scorecards():
    """Get all stored scorecards (Admin only)."""
    try:
        scorecards = get_all_scorecards()
        count = get_scorecard_count()
        return jsonify({
            'status': 'success',
            'count': count,
            'scorecards': scorecards
        })
    except Exception as e:
        return jsonify({'error': str(e), 'status': 'error'}), 500


@app.route('/api/scorecards/<int:record_id>', methods=['DELETE'])
@require_auth
def remove_scorecard(record_id):
    """Delete a scorecard entry (Admin only)."""
    try:
        delete_scorecard(record_id)
        return jsonify({'status': 'success', 'message': f'Record {record_id} deleted.'})
    except Exception as e:
        return jsonify({'error': str(e), 'status': 'error'}), 500


@app.route('/api/stats', methods=['GET'])
def stats():
    """Get basic stats."""
    try:
        count = get_scorecard_count()
        return jsonify({
            'status': 'success',
            'total_scorecards': count,
            'pyzbar_available': QR_AVAILABLE
        })
    except Exception as e:
        return jsonify({'error': str(e), 'status': 'error'}), 500


if __name__ == '__main__':
    print("=" * 60)
    print("  GO Classes - Scholarship Score Card Checker")
    qr_status = "Available" if QR_AVAILABLE else "Not available (will use image hash only)"
    print(f"  QR Code Scanner: {qr_status}")
    print("  Server starting at http://localhost:5000")
    print("=" * 60)
    app.run(debug=True, port=5000)
