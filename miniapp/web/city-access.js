(() => {
  const entry=document.getElementById('cityGameEntry');
  if(!entry)return;
  const initData=window.Telegram?.WebApp?.initData;
  if(!initData)return;
  fetch('/api/city/access',{headers:{'X-Telegram-Init-Data':initData}})
    .then(r=>r.ok?r.json():null)
    .then(data=>{if(data?.allowed)entry.hidden=false})
    .catch(()=>{});
})();
