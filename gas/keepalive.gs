function keepAlive() {
  // Renderの /healthz に5分ごとにアクセスしてスリープを回避する
  var url = 'https://YOUR-RENDER-APP.onrender.com/healthz';
  var options = {
    method: 'get',
    muteHttpExceptions: true
  };
  var response = UrlFetchApp.fetch(url, options);
  Logger.log('status=' + response.getResponseCode());
}

/*
トリガー設定手順:
1) Apps Script エディタの「トリガー」を開く
2) 「トリガーを追加」を押す
3) 実行する関数: keepAlive
4) イベントのソース: 時間主導型
5) 時間ベースのトリガーのタイプ: 分タイマー
6) 間隔: 5分おき
*/
