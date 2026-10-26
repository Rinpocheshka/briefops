import {createAuthClient} from '@neondatabase/auth';
import {BetterAuthVanillaAdapter} from '@neondatabase/auth/vanilla/adapters';

let client, cachedToken='', tokenUntil=0;
const active=location.pathname==='/workspace'||location.pathname==='/login';
const ready=active?(async()=>{
  const response=await fetch('/api/auth-config');
  const config=await response.json();
  if(!response.ok||!config.enabled)throw new Error('Рабочий кабинет ещё настраивается. Попробуйте позже.');
  client=createAuthClient(config.base_url,{adapter:BetterAuthVanillaAdapter({fetchOptions:{credentials:'include'}})});
})():Promise.resolve();

async function token(force=false){
  if(force){cachedToken="";tokenUntil=0;}
  await ready;
  if(cachedToken&&Date.now()<tokenUntil)return cachedToken;
  const {data,error}=await client.token();
  if(error||!data?.token){if(location.pathname==='/workspace')location.replace('/login');throw new Error('Сессия недоступна. Войдите в рабочий кабинет ещё раз.');}
  cachedToken=data.token;tokenUntil=Date.now()+5*60*1000;
  return cachedToken;
}
window.briefopsAuth={ready,token,async signOut(){await ready;const result=await client.signOut();if(result.error)throw new Error('Не удалось завершить сеанс. Попробуйте ещё раз.');cachedToken='';location.replace('/login');}};
// A rejected configuration must not create an unhandled promise on the public demo.
ready.catch(()=>{});

if(location.pathname==='/login'){
  const form=document.getElementById('loginForm');
  const message=document.getElementById('loginMessage');
  const code=document.getElementById('otpGroup');
  const button=document.getElementById('loginSubmit');
  const resend=document.getElementById('resendCode');
  let sent=false, email='',resendAt=0;
  async function sendCode(){
    const result=await client.emailOtp.sendVerificationOtp({email,type:'sign-in'});
    if(result.error)throw new Error('Не удалось отправить код. Проверьте адрес и попробуйте позже.');
    resendAt=Date.now()+60000;resend.hidden=false;resend.disabled=true;
    setTimeout(()=>{resend.disabled=false;},60000);
  }
  resend.addEventListener('click',async()=>{
    if(Date.now()<resendAt)return;resend.disabled=true;
    try{await sendCode();message.textContent='Новый код отправлен. Введите его в поле «Код из письма» ниже.';form.elements.otp.value='';form.elements.otp.focus();}
    catch(error){message.textContent=error.message;resend.disabled=false;}
  });
  form.addEventListener('submit',async event=>{
    event.preventDefault();button.disabled=true;message.textContent='';
    try{
      await ready;
      if(!sent){
        email=form.elements.email.value.trim().toLowerCase();
        await sendCode();
        sent=true;code.hidden=false;form.elements.email.readOnly=true;
        form.elements.otp.required=true;button.textContent='Войти';
        message.textContent='Код отправлен на вашу почту. Введите его в поле «Код из письма» ниже и нажмите «Войти».';
        form.elements.otp.focus();
      }else{
        const result=await client.signIn.emailOtp({email,otp:form.elements.otp.value.trim()});
        if(result.error)throw new Error('Код не подошёл или истёк. Проверьте код из последнего письма.');
        const bearer=await token();
        const check=await fetch('/api/workspace/state',{headers:{Authorization:'Bearer '+bearer}});
        if(!check.ok){await client.signOut();cachedToken='';throw new Error('У этого аккаунта нет доступа к рабочей области.');}
        location.replace('/workspace');
      }
    }catch(error){message.textContent=error.message||'Не удалось войти. Попробуйте ещё раз.';}
    finally{button.disabled=false;}
  });
  document.getElementById('changeEmail').addEventListener('click',()=>{
    sent=false;code.hidden=true;resend.hidden=true;form.elements.email.readOnly=false;form.elements.otp.required=false;
    form.elements.otp.value='';button.textContent='Получить код';message.textContent='';
  });
}
