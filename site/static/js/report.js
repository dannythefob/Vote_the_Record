// Corrections form helpers: prefill the item ID from ?item=, and explain ?reason= on the
// error page. Works without this script too; it only fills in and explains.
(function () {
  const params = new URLSearchParams(window.location.search);
  const item = document.getElementById("item");
  if (item && params.get("item")) item.value = params.get("item").slice(0, 200);
  const reasons = {
    "missing-problem": "Please describe what's wrong in at least a sentence.",
    "too-long": "The report was longer than we can accept. Please shorten it.",
    "bad-item": "The item ID didn't look right. Leave it blank if you're not sure.",
    "bad-source": "The source link needs to start with http:// or https://.",
    unavailable: "The report form isn't switched on for this version of the site yet. Nothing was saved.",
    format: "The form was sent in a way we couldn't read. Please try again from the form page.",
  };
  const msg = document.getElementById("report-error");
  if (msg && reasons[params.get("reason")]) msg.textContent = reasons[params.get("reason")];
})();
