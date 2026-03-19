// ===== GO Classes Score Card Checker — Frontend JS =====

const API_BASE = '';
let adminToken = sessionStorage.getItem('adminToken');

// ===== STATE =====
let selectedFile = null;

// ===== DOM Elements =====
const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const filePreview = document.getElementById('filePreview');
const filePreviewName = document.getElementById('filePreviewName');
const filePreviewSize = document.getElementById('filePreviewSize');
const uploadForm = document.getElementById('uploadForm');
const submitBtn = document.getElementById('submitBtn');

const resultPlaceholder = document.getElementById('resultPlaceholder');
const resultApproved = document.getElementById('resultApproved');
const resultDuplicate = document.getElementById('resultDuplicate');

const totalCount = document.getElementById('totalCount');
const searchInput = document.getElementById('searchInput');
const tableBody = document.getElementById('tableBody');
const emptyState = document.getElementById('emptyState');

// ===== TAB NAVIGATION =====
document.querySelectorAll('.nav-tab').forEach(tab => {
    tab.addEventListener('click', () => {
        const target = tab.dataset.tab;
        document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        document.getElementById(target).classList.add('active');

        if (target === 'dashboard') {
            if (!adminToken) {
                const pwd = prompt("Enter Admin Password to view Dashboard:");
                if (pwd) {
                    adminToken = pwd;
                    sessionStorage.setItem('adminToken', pwd);
                    loadDashboard();
                } else {
                    // Revert tab visually if cancelled
                    setTimeout(() => document.querySelector('.nav-tab[data-target="upload"]').click(), 10);
                }
            } else {
                loadDashboard();
            }
        }
    });
});

// ===== DROP ZONE =====
dropZone.addEventListener('click', () => fileInput.click());

dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('drag-over');
});

dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('drag-over');
});

dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    const files = e.dataTransfer.files;
    if (files.length > 0) {
        handleFileSelect(files[0]);
    }
});

fileInput.addEventListener('change', () => {
    if (fileInput.files.length > 0) {
        handleFileSelect(fileInput.files[0]);
    }
});

async function handleFileSelect(file) {
    const allowedTypes = ['image/png', 'image/jpeg', 'image/jpg', 'image/bmp', 'image/gif', 'image/tiff', 'image/webp', 'application/pdf'];
    if (!allowedTypes.includes(file.type)) {
        showToast('Invalid file type. Please upload an image or PDF file.', 'error');
        return;
    }

    selectedFile = file;
    filePreviewName.textContent = file.name;
    filePreviewSize.textContent = formatFileSize(file.size);
    filePreview.classList.add('show');
    dropZone.style.display = 'none';

    // Start auto-extraction
    await autoExtractDetails(file);
}

// Removed raw regex patterns, using a line-by-line approach for better accuracy

function parseExtractedText(text, qrData = null) {
    let name = '';
    let regNo = '';
    let score = '';

    // Step 1: Attempt to pull perfect data from the embedded QR code
    if (qrData) {
        const qrRegMatch = qrData.match(/\b([A-Z]{2}\d{2}[A-Z0-9]{5,10})\b/i);
        if (qrRegMatch) regNo = qrRegMatch[1].toUpperCase();
        
        const qrScoreMatch = qrData.match(/(?:score|marks)[\s:="']*(\d{2,4})/i);
        if (qrScoreMatch) score = qrScoreMatch[1].trim();
        
        try {
            const qrObj = JSON.parse(qrData);
            if (qrObj.name || qrObj.student_name) name = qrObj.name || qrObj.student_name;
            if (qrObj.reg || qrObj.registration) regNo = qrObj.reg || qrObj.registration;
            if (qrObj.score || qrObj.gate_score) score = qrObj.score || qrObj.gate_score;
        } catch(e) {} // Not JSON
    }

    // Step 2: Parse raw text for any missing pieces
    const lines = text ? text.split('\n').map(l => l.trim()).filter(l => l.length > 0) : [];
    
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        
        // Match Name
        if (!name && /^(?:Name of Candidate|Name|Candidate Name)$/i.test(line) && i + 1 < lines.length) {
            name = lines[i + 1];
        } else if (!name && /^(?:Name of Candidate|Name|Candidate Name)\s*[\:\-]\s*(.+)$/i.test(line)) {
            name = line.match(/^(?:Name of Candidate|Name|Candidate Name)\s*[\:\-]\s*(.+)$/i)[1];
        }
        
        // Match Reg No
        if (!regNo && /^(?:Registration Number|Registration No\.?)$/i.test(line) && i + 1 < lines.length) {
            regNo = lines[i + 1];
        } else if (!regNo && /^(?:Registration Number|Registration No\.?)\s*[\:\-]\s*(.+)$/i.test(line)) {
            regNo = line.match(/^(?:Registration Number|Registration No\.?)\s*[\:\-]\s*(.+)$/i)[1];
        }
        
        // Match Score
        if (!score && /^(?:GATE Score|Score)$/i.test(line) && i + 1 < lines.length) {
            score = lines[i + 1];
        } else if (!score && /^(?:GATE Score|Score)\s*[\:\-]\s*(\d+)$/i.test(line)) {
            score = line.match(/^(?:GATE Score|Score)\s*[\:\-]\s*(\d+)$/i)[1];
        }
    }
    
    // Fallbacks if line-by-line fails
    
    // SPECIAL CASE: Official GATE Scorecard PDFs often hide labels completely.
    // They output purely structured data where:
    // lines[0] = RegNo (e.g., DA25S54035130)
    // lines[1] = Subject
    // lines[2] = Name
    // lines[3] = Rank
    // lines[4] = Hash
    // lines[5, 6, 7] = Cutoffs (float)
    // lines[8] = GATE Score (int)
    if (!name && !regNo && lines.length >= 10 && /^[A-Z]{2}\d{2}[A-Z0-9]+$/i.test(lines[0])) {
        // We caught the official GATE PDF labelless format!
        regNo = lines[0].toUpperCase();
        name = lines[2].replace(/[^a-zA-Z\s]/g, '').trim();
        
        // Find the GATE score (first valid integer <= 1000 after the hash)
        // We start searching after the Rank (index 3) and Hash (index 4)
        for (let j = 5; j < lines.length; j++) {
            if (/^\d{2,4}$/.test(lines[j])) {
                const val = parseInt(lines[j], 10);
                if (val > 0 && val <= 1000) {
                    score = val.toString();
                    break;
                }
            }
        }
    } else {
        // General text Regex Fallbacks
        if (!name) {
            const nameMatch = text.match(/(?:Name of Candidate|Name)\s*[:\-]?\s*([A-Z][a-z]+ [A-Z][a-z]+)/i);
            if (nameMatch) name = nameMatch[1].trim();
        }
        if (!regNo) {
            const genReg = text.match(/\b([A-Z]{2}\d{2}[A-Z0-9]{5,10})\b/i);
            if (genReg) regNo = genReg[1].toUpperCase();
        }
        if (!score) {
            const scoreMatch = text.match(/(?:GATE Score|Score)\s*[:\-]?\s*(\d{2,4})/i);
            if (scoreMatch) score = scoreMatch[1].trim();
        }
    }
    
    // Fill form
    if (name && name.length > 2) document.getElementById('studentName').value = name;
    if (regNo) document.getElementById('registrationNo').value = regNo;
    if (score) document.getElementById('gateScore').value = parseInt(score).toString(); // clean up any extra chars
    
    if (name || regNo || score) {
        showToast('Document scanned and details auto-filled!', 'success');
    } else {
        showToast('Could not automatically detect details. Please enter manually.', 'error');
    }
}

async function autoExtractDetails(file) {
    const scanStatus = document.getElementById('scanStatus');
    scanStatus.style.display = 'flex';
    scanStatus.querySelector('.scan-text').textContent = 'Scanning document (QR & Text) for details...';
    
    // Reset previous inputs
    document.getElementById('studentName').value = '';
    document.getElementById('registrationNo').value = '';
    document.getElementById('gateScore').value = '';
    
    try {
        // ALWAYS pass file to backend to fetch embedded QR payload and native PDF text if available
        const formData = new FormData();
        formData.append('file', file);
        const res = await fetch(`${API_BASE}/api/extract`, { method: 'POST', body: formData });
        const data = await res.json();
        
        let extractedText = data.text || '';
        let extractedQr = data.qr_data || null;

        if (file.type !== 'application/pdf') {
            // Because images don't yield precise text from backend, use Tesseract to complement the QR data
            scanStatus.querySelector('.scan-text').textContent = 'Running OCR on image...';
            const result = await Tesseract.recognize(file, 'eng');
            extractedText = result.data.text;
        }
        
        parseExtractedText(extractedText, extractedQr);
        
    } catch (err) {
        console.error("Extraction error:", err);
    } finally {
        scanStatus.style.display = 'none';
    }
}

document.getElementById('removeFile').addEventListener('click', () => {
    clearFileSelection();
});

function clearFileSelection() {
    selectedFile = null;
    fileInput.value = '';
    filePreview.classList.remove('show');
    dropZone.style.display = 'block';
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

// ===== FORM SUBMISSION =====
uploadForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    if (!selectedFile) {
        showToast('Please select a score card image first.', 'error');
        return;
    }

    const studentName = document.getElementById('studentName').value.trim();
    if (!studentName) {
        showToast('Student name is required.', 'error');
        return;
    }

    // Build form data
    const formData = new FormData();
    formData.append('file', selectedFile);
    formData.append('student_name', studentName);
    formData.append('registration_no', document.getElementById('registrationNo').value.trim());
    formData.append('gate_score', document.getElementById('gateScore').value.trim());

    // Show loading
    submitBtn.classList.add('loading');
    submitBtn.disabled = true;

    try {
        const response = await fetch(`${API_BASE}/api/upload`, {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        // Hide all results first
        resultPlaceholder.style.display = 'none';
        resultApproved.classList.remove('show');
        resultDuplicate.classList.remove('show');

        if (data.status === 'approved') {
            // Show approved result
            document.getElementById('approvedName').textContent = data.record.student_name;
            document.getElementById('approvedRegNo').textContent = data.record.registration_no || 'N/A';
            document.getElementById('approvedScore').textContent = data.record.gate_score || 'N/A';
            document.getElementById('approvedQR').textContent = data.record.qr_data_found ? '✓ Found' : '✗ Not Found';
            document.getElementById('approvedHash').textContent = data.record.image_hash || 'N/A';
            resultApproved.classList.add('show');
            showToast('✅ Scholarship approved! Score card verified.', 'success');
            updateStats();

        } else if (data.status === 'duplicate') {
            // Show duplicate result
            document.getElementById('dupOriginalName').textContent = data.existing_record.student_name;
            document.getElementById('dupOriginalRegNo').textContent = data.existing_record.registration_no || 'N/A';
            document.getElementById('dupOriginalScore').textContent = data.existing_record.gate_score || 'N/A';
            document.getElementById('dupOriginalDate').textContent = formatDate(data.existing_record.uploaded_at);
            document.getElementById('dupMatchType').textContent = data.match_type;
            resultDuplicate.classList.add('show');
            showToast('🚨 Duplicate detected! This score card was already used.', 'error');

        } else if (data.status === 'error') {
            showToast(data.error || 'Something went wrong.', 'error');
        }

    } catch (err) {
        console.error(err);
        showToast('Network error. Is the server running?', 'error');
    } finally {
        submitBtn.classList.remove('loading');
        submitBtn.disabled = false;
    }
});

// ===== DASHBOARD =====
async function loadDashboard() {
    if (!adminToken) return; // safety
    
    try {
        const response = await fetch(`${API_BASE}/api/scorecards`, {
            headers: { 'Authorization': `Bearer ${adminToken}` }
        });
        
        if (response.status === 401) {
            showToast('Incorrect Admin Password', 'error');
            adminToken = null;
            sessionStorage.removeItem('adminToken');
            switchTab('upload');
            return;
        }
        
        const data = await response.json();

        if (data.status === 'success') {
            renderTable(data.scorecards);
            totalCount.textContent = data.count;
        }
    } catch (err) {
        console.error(err);
        showToast('Failed to load dashboard data.', 'error');
    }
}

function renderTable(scorecards) {
    if (scorecards.length === 0) {
        tableBody.innerHTML = '';
        emptyState.style.display = 'block';
        document.querySelector('.table-container').style.display = 'none';
        return;
    }

    emptyState.style.display = 'none';
    document.querySelector('.table-container').style.display = 'block';

    tableBody.innerHTML = scorecards.map((sc, index) => `
        <tr>
            <td style="color: var(--text-primary); font-weight: 600;">${sc.student_name}</td>
            <td>${sc.registration_no || '—'}</td>
            <td>${sc.gate_score || '—'}</td>
            <td>
                <span class="qr-status ${sc.qr_data ? 'found' : 'not-found'}">
                    ${sc.qr_data ? '✓ Found' : '✗ N/A'}
                </span>
            </td>
            <td style="font-family: monospace; font-size: 11px; color: var(--text-muted);">
                ${sc.image_hash ? sc.image_hash.substring(0, 12) + '...' : '—'}
            </td>
            <td>${formatDate(sc.uploaded_at)}</td>
            <td>
                <button type="button" class="btn-delete" onclick="deleteRecord(event, ${sc.id})" title="Delete record">
                    🗑️ Delete
                </button>
            </td>
        </tr>
    `).join('');
}

async function deleteRecord(event, id) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    // confirmation removed to bypass silent browser blocking

    try {
        const response = await fetch(`${API_BASE}/api/scorecards/${id}`, { 
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${adminToken}` }
        });
        const data = await response.json();

        if (data.status === 'success') {
            showToast('Record deleted successfully.', 'success');
            loadDashboard();
            updateStats();
        } else {
            showToast(data.error || 'Failed to delete.', 'error');
        }
    } catch (err) {
        showToast('Network error.', 'error');
    }
}

// ===== SEARCH =====
searchInput.addEventListener('input', () => {
    const query = searchInput.value.toLowerCase();
    const rows = tableBody.querySelectorAll('tr');
    rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(query) ? '' : 'none';
    });
});

// ===== STATS =====
async function updateStats() {
    try {
        const response = await fetch(`${API_BASE}/api/stats`);
        const data = await response.json();
        if (data.status === 'success') {
            totalCount.textContent = data.total_scorecards;
        }
    } catch (err) {
        console.error(err);
    }
}

// ===== TOAST =====
function showToast(message, type = 'success') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `<span>${type === 'success' ? '✅' : '❌'}</span> ${message}`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.animation = 'toastOut 0.4s ease forwards';
        setTimeout(() => toast.remove(), 400);
    }, 4000);
}

// ===== HELPERS =====
function formatDate(dateStr) {
    if (!dateStr) return '—';
    try {
        const d = new Date(dateStr);
        return d.toLocaleDateString('en-IN', {
            day: '2-digit',
            month: 'short',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    } catch {
        return dateStr;
    }
}

// ===== INIT =====
updateStats();
