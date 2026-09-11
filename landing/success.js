(function () {
  var params = new URLSearchParams(location.search);
  var checkoutId = params.get('checkout_id');
  var target = 'http://127.0.0.1:8765/?checkout=success';
  if (checkoutId) target += '&checkout_id=' + encodeURIComponent(checkoutId);
  var link = document.getElementById('returnApp');
  if (link) link.href = target;
  setTimeout(function () { location.href = target; }, 1200);
})();
