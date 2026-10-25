import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {createHash,createHmac} from 'node:crypto';
import assert from 'node:assert/strict';

const secret='test-only-secret-'.repeat(3), values=new Map([['BRIEFOPS_MAIL_SECRET',secret]]);
let sent=0, interrupt=false;
const scope={console, PropertiesService:{getScriptProperties:()=>({getProperty:k=>values.get(k),setProperty:(k,v)=>values.set(k,v)})},
  ContentService:{MimeType:{JSON:'json'},createTextOutput:body=>({setMimeType:()=>JSON.parse(body)})},
  LockService:{getScriptLock:()=>({tryLock:()=>true,releaseLock(){}})},
  MailApp:{getRemainingDailyQuota:()=>50,sendEmail(){sent++;if(interrupt)throw new Error('Ambiguous external failure');}},
  Utilities:{Charset:{UTF_8:'utf8'},DigestAlgorithm:{SHA_256:'sha256'},
    computeDigest:(_,value)=>Array.from(createHash('sha256').update(value).digest()),
    computeHmacSha256Signature:(value,key)=>Array.from(createHmac('sha256',key).update(value).digest())}};
vm.createContext(scope);vm.runInContext(readFileSync('integrations/google-mail/Code.gs','utf8'),scope);
function call(id,changes={},badSignature=false){
  const payload=JSON.stringify({id,to:'test@example.com',subject:'Approved test',body:'Approved body',issued_at:Math.floor(Date.now()/1000),...changes});
  const signature=badSignature?'bad':createHmac('sha256',secret).update(payload).digest('hex');
  return scope.doPost({postData:{contents:JSON.stringify({payload,signature})}});
}
const id='a'.repeat(32), other='b'.repeat(32);
assert.equal(call(id).status,'sent');assert.equal(sent,1);
assert.equal(call(id).status,'sent');assert.equal(sent,1);
assert.equal(call(id,{body:'Changed'}).status,'conflict');assert.equal(sent,1);
assert.equal(call(other,{},true).status,'rejected');assert.equal(sent,1);
assert.equal(call(other,{to:'a@example.com,b@example.com'}).status,'rejected');
assert.equal(call(other,{issued_at:1}).status,'rejected');
interrupt=true;assert.equal(call(other).status,'uncertain');assert.equal(sent,2);
interrupt=false;assert.equal(call(other).status,'uncertain');assert.equal(sent,2);
console.log('MAIL BRIDGE OK: signatures, expiry, one recipient, payload conflicts, persistent deduplication, ambiguous sends never repeated');
