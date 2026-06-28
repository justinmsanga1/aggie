/**
 * Google Apps Script — PSN Manager Accounts Backup
 *
 * HOW TO DEPLOY:
 * 1. Go to https://script.google.com
 * 2. Create a new project, paste this code
 * 3. Run setupSheet() once to authorize and create headers
 * 4. Deploy > New deployment > Web app
 *    - Execute as: Me
 *    - Who has access: Anyone
 * 5. Copy the web app URL → paste into PSN Manager app
 */

function setupSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getActiveSheet() || ss.insertSheet('Accounts Backup');
  sheet.appendRow([
    'Timestamp', 'Account ID', 'Email', 'Region', 'Condition', 'Status',
    'Purchase Cost', 'PSN Deposits', 'PSN Game Purchases', 'Revenue',
    'Games', 'Notes', 'PS4 Slots Available', 'PS5 Slots Available',
    'Next Deactivation', 'Created At'
  ]);
  sheet.setFrozenRows(1);
  const bold = sheet.getRange('1:1');
  bold.setFontWeight('bold');
}

function doPost(e) {
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const sheet = ss.getActiveSheet() || ss.insertSheet('Accounts Backup');

    const data = JSON.parse(e.postData.contents);
    const accounts = data.accounts || [];
    const timestamp = new Date().toISOString();

    const rows = accounts.map(a => [
      timestamp,
      a.id,
      a.email,
      a.region,
      a.condition || 'clean',
      a.status || 'active',
      Number(a.purchaseCost) || 0,
      Number(a.psnDeposits) || 0,
      Number(a.psnGamePurchases) || 0,
      Number(a.revenue) || 0,
      (a.games || []).join(', '),
      a.notes || '',
      (a.slots?.ps4 || []).filter(s => s.status === 'available').length,
      (a.slots?.ps5 || []).filter(s => s.status === 'available').length,
      a.nextDeactivation || '',
      a.createdAt || ''
    ]);

    if (rows.length > 0) {
      // Check if headers exist, add them if sheet is empty
      if (sheet.getLastRow() === 0) {
        setupSheet();
      }
      sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows);
    }

    return ContentService
      .createTextOutput(JSON.stringify({ success: true, count: accounts.length }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ success: false, error: err.message }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

function doGet() {
  return ContentService
    .createTextOutput(JSON.stringify({ status: 'ok', message: 'PSN Manager Backup Web App is running.' }))
    .setMimeType(ContentService.MimeType.JSON);
}
