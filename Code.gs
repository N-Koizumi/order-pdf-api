/**
 * 博報堂アイ・スタジオ 発注書自動処理 Google Apps Script
 * 親フォルダID: 1I_3NG2AyVwoFJT_2ZXlNdhPIcpyvYhGh (H系発注書自動処理)
 */

// 親フォルダID
const ROOT_FOLDER_ID = '1I_3NG2AyVwoFJT_2ZXlNdhPIcpyvYhGh';

// クラウド処理APIのURL（Cloud Runデプロイ後に設定）
const API_URL = 'https://YOUR_CLOUD_RUN_SERVICE_URL/process-pdf';

/**
 * フォルダ内の未処理PDFをすべて自動処理して仕分けるメイン関数
 * （トリガー設定で1分〜5分間隔で定期実行）
 */
function autoProcessOrders() {
  const rootFolder = DriveApp.getFolderById(ROOT_FOLDER_ID);
  
  // 1. 01_未処理 フォルダを取得
  const unprocessedFolders = rootFolder.getFoldersByName('01_未処理');
  if (!unprocessedFolders.hasNext()) {
    console.log('01_未処理 フォルダが見つかりません。');
    return;
  }
  const unprocessedFolder = unprocessedFolders.next();

  // 2. 02_完了 と 03_処理済み原本 フォルダを取得（無ければ自動作成）
  const completedRoot = getOrCreateFolder(rootFolder, '02_完了');
  const archiveRoot = getOrCreateFolder(rootFolder, '03_処理済み原本');

  // 3. 未処理PDFを走査
  const files = unprocessedFolder.getFiles();
  let count = 0;

  while (files.hasNext()) {
    const file = files.next();
    const filename = file.getName();
    
    if (filename.toLowerCase().endsWith('.pdf') && !filename.startsWith('【完成】')) {
      console.log(`📄 処理開始: ${filename}`);
      try {
        processSingleFile(file, completedRoot, archiveRoot);
        count++;
      } catch (err) {
        console.error(`❌ エラー (${filename}): ${err.message}`);
      }
    }
  }

  if (count > 0) {
    console.log(`🎉 合計 ${count} 件の処理が完了しました！`);
  }
}

/**
 * 1件のファイルをAPIに送信して完成版を保存し、原本を退避する
 */
function processSingleFile(file, completedRoot, archiveRoot) {
  const fileBlob = file.getBlob();
  const filename = file.getName();

  // Cloud Run API へ送信 (multipart/form-data)
  const boundary = '----WebKitFormBoundary' + Utilities.getUuid();
  let payload = '';
  
  // ファイルパートの構築
  payload += '--' + boundary + '\r\n';
  payload += 'Content-Disposition: form-data; name="file"; filename="' + filename + '"\r\n';
  payload += 'Content-Type: application/pdf\r\n\r\n';

  const headerBytes = Utilities.newBlob(payload).getBytes();
  const fileBytes = fileBlob.getBytes();
  const footerBytes = Utilities.newBlob('\r\n--' + boundary + '--\r\n').getBytes();

  const fullBodyBytes = [].concat(
    Array.from(headerBytes),
    Array.from(fileBytes),
    Array.from(footerBytes)
  );

  const options = {
    method: 'post',
    contentType: 'multipart/form-data; boundary=' + boundary,
    payload: fullBodyBytes,
    muteHttpExceptions: true
  };

  const response = UrlFetchApp.fetch(API_URL, options);
  const responseCode = response.getResponseCode();
  const responseText = response.getContentText();

  if (responseCode !== 200) {
    throw new Error(`API呼び出し失敗 (${responseCode}): ${responseText}`);
  }

  const result = JSON.parse(responseText);
  if (!result.success) {
    throw new Error(result.error || '不明なエラー');
  }

  const clientName = result.client_name || 'その他';
  const yearMonth = result.year_month || 'その他';
  const outputFilename = result.output_filename || `【完成】${filename}`;
  const pdfBytes = Utilities.base64Decode(result.pdf_base64);
  const outputBlob = Utilities.newBlob(pdfBytes, 'application/pdf', outputFilename);

  // 1. 02_完了 / {年月} / {広告主名} / に完成PDFを保存
  const ymCompletedFolder = getOrCreateFolder(completedRoot, yearMonth);
  const clientCompletedFolder = getOrCreateFolder(ymCompletedFolder, clientName);
  clientCompletedFolder.createFile(outputBlob);
  console.log(`✔ 完成版保存完了: ${yearMonth} / ${clientName} / ${outputFilename}`);

  // 2. 03_処理済み原本 / {年月} / {広告主名} / に元ファイルを移動
  const ymArchiveFolder = getOrCreateFolder(archiveRoot, yearMonth);
  const clientArchiveFolder = getOrCreateFolder(ymArchiveFolder, clientName);
  file.moveTo(clientArchiveFolder);
  console.log(`📦 原本移動完了: ${yearMonth} / ${clientName} / ${filename}`);
}

/**
 * サブフォルダを取得または新規作成するヘルパー関数
 */
function getOrCreateFolder(parentFolder, folderName) {
  const folders = parentFolder.getFoldersByName(folderName);
  if (folders.hasNext()) {
    return folders.next();
  } else {
    return parentFolder.createFolder(folderName);
  }
}
