/** BriefOps send-only bridge. No GmailApp, mailbox reads, or inbox triggers. */
function authorizeMail() {
  console.log('Remaining recipients today: ' + MailApp.getRemainingDailyQuota());
}

function doGet() {
  return json_({service: 'briefops-mail', configured: !!PropertiesService.getScriptProperties().getProperty('BRIEFOPS_MAIL_SECRET')});
}

function doPost(e) {
  const props = PropertiesService.getScriptProperties();
  const secret = props.getProperty('BRIEFOPS_MAIL_SECRET') || '';
  let delivery;
  try {
    if (secret.length < 32 || !e.postData || e.postData.contents.length > 25000) throw new Error('Invalid request');
    const envelope = JSON.parse(e.postData.contents);
    if (typeof envelope.payload !== 'string' || typeof envelope.signature !== 'string') throw new Error('Invalid request');
    const signature = hex_(Utilities.computeHmacSha256Signature(envelope.payload, secret, Utilities.Charset.UTF_8));
    if (!equal_(signature, envelope.signature)) throw new Error('Invalid signature');
    delivery = JSON.parse(envelope.payload);
    if (!Number.isInteger(delivery.issued_at) || Math.abs(Date.now()/1000 - delivery.issued_at) > 300) throw new Error('Expired request');
    if (!/^[a-f0-9]{32}$/.test(delivery.id) || typeof delivery.to !== 'string' || delivery.to.length > 254 ||
        !/^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,63}$/.test(delivery.to) ||
        typeof delivery.subject !== 'string' || delivery.subject.length > 180 || /[\r\n]/.test(delivery.subject) ||
        typeof delivery.body !== 'string' || !delivery.body.trim() || delivery.body.length > 5000) throw new Error('Invalid message');
  } catch (_) {
    return json_({ok:false, status:'rejected'});
  }
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) return json_({ok:false, status:'busy'});
  try {
    const key = 'delivery_' + delivery.id;
    const hash = hex_(Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,
      JSON.stringify([delivery.to, delivery.subject, delivery.body]), Utilities.Charset.UTF_8));
    const previous = props.getProperty(key);
    if (previous) {
      const saved = JSON.parse(previous);
      if (saved.hash !== hash) return json_({ok:false, status:'conflict'});
      return json_({ok:saved.status === 'sent', status:saved.status === 'sent' ? 'sent' : 'uncertain', id:delivery.id, replayed:true});
    }
    if (MailApp.getRemainingDailyQuota() < 1) return json_({ok:false, status:'quota'});
    // Persist before the external call. An interrupted send must never be repeated blindly.
    props.setProperty(key, JSON.stringify({hash:hash, status:'pending', at:Date.now()}));
    try {
      MailApp.sendEmail({to:delivery.to, subject:delivery.subject, body:delivery.body,
                        name:'World of Vibecraft', replyTo:'harebolka@gmail.com'});
      props.setProperty(key, JSON.stringify({hash:hash, status:'sent', at:Date.now()}));
      return json_({ok:true, status:'sent', id:delivery.id});
    } catch (_) {
      return json_({ok:false, status:'uncertain', id:delivery.id});
    }
  } finally {
    lock.releaseLock();
  }
}

function hex_(bytes) { return bytes.map(function(b) { return ('0' + ((b+256)%256).toString(16)).slice(-2); }).join(''); }
function equal_(a,b) { let different = a.length ^ b.length; for(let i=0;i<a.length;i++) different |= a.charCodeAt(i) ^ (b.charCodeAt(i)||0); return different === 0; }
function json_(body) { return ContentService.createTextOutput(JSON.stringify(body)).setMimeType(ContentService.MimeType.JSON); }
