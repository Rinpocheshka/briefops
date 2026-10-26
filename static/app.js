"use strict";
const privateWorkspace=location.pathname==='/workspace';
async function apiFetch(path,options={}){
 const headers={...(options.headers||{})};
 if(privateWorkspace){headers.Authorization='Bearer '+await window.briefopsAuth.token();path=path.replace('/api/','/api/workspace/');}
 let response=await fetch(path,{...options,headers,cache:'no-store'});
 if(privateWorkspace&&response.status===401){headers.Authorization='Bearer '+await window.briefopsAuth.token(true);response=await fetch(path,{...options,headers,cache:'no-store'});}
 if(privateWorkspace&&response.status===401){location.replace('/login');throw new Error('Войдите в рабочий кабинет');}
 return response;
}

const paths={inbox:'<path d="M4 4h16v16H4z"/><path d="M4 13h5l2 3h2l2-3h5"/>',layers:'<path d="m12 3 10 5-10 5L2 8z"/><path d="m2 12 10 5 10-5M2 16l10 5 10-5"/>',workflow:'<rect x="9" y="2" width="6" height="6" rx="1"/><rect x="2" y="16" width="6" height="6" rx="1"/><rect x="16" y="16" width="6" height="6" rx="1"/><path d="M12 8v4M5 16v-4h14v4"/>',clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',plus:'<path d="M12 5v14M5 12h14"/>',search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',download:'<path d="M12 3v12m-4-4 4 4 4-4M4 16v5h16v-5"/>','check-circle':'<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',copy:'<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V4H4v12h4"/>',x:'<path d="m6 6 12 12M6 18 18 6"/>',info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',sparkles:'<path d="m12 2 2.7 7.3L22 12l-7.3 2.7L12 22l-2.7-7.3L2 12l7.3-2.7z"/>',edit:'<path d="m15 4 5 5M4 20l5-1L21 7l-5-5L4 14z"/>',check:'<path d="m5 12 4 4L19 6"/>'};
const icon=name=>`<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name]||paths.info}</svg>`;
function icons(root=document){root.querySelectorAll('[data-icon]').forEach(el=>{el.innerHTML=icon(el.dataset.icon)})}
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=value=>value?`${new Intl.NumberFormat('ru-RU').format(value)} ₽`:'Бюджет не указан';
const labels={queued:'В очереди',processing:'В обработке',ready:'Ждёт проверки',needs_info:'Нужны уточнения',duplicate:'Повтор',retry:'Повторная попытка',failed:'Ошибка',approved:'Согласован',sent:'Отправлено',sending:'Отправляется',delivery_failed:'Ошибка отправки',delivery_uncertain:'Нужна проверка отправки'};
const sources={website:'Форма сайта',email:'Почта',telegram:'Telegram',manual:'Вручную',n8n:'n8n'};
const $=id=>document.getElementById(id);
let newLeadId=null;
let state=null,selected=null,view='inbox',filter='review',query='',detailTab='review',dirty=false,editing=false,lastDetailVersion='',busy=false,toastTimer,displayedVersion=0,refreshing=false,refreshAgain=false,stateTag="",refreshFailed=false;
function timeAgo(ts){const n=Math.max(0,Math.floor((Date.now()/1000-ts)/60));return n<1?'только что':n<60?`${n} мин назад`:`${Math.floor(n/60)} ч назад`}
function clock(ts){return new Date(ts*1000).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}
function badge(status){return `<span class="badge ${esc(status)}">${esc(labels[status]||status)}</span>`}
function notify(message,error=false){$('toast').textContent=message;$('toast').className=`toast visible${error?' error':''}`;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').className='toast',4500)}
async function post(path,payload={}){const response=await apiFetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Briefops-CSRF':state.csrf},body:JSON.stringify(payload)});const result=await response.json();if(!response.ok)throw new Error(result.error||'Не удалось выполнить действие');return result}
async function refresh(){
 if(refreshing){refreshAgain=true;return}refreshing=true;
 try{
  const response=await apiFetch('/api/state',{headers:stateTag?{'If-None-Match':stateTag}:{}});
  if(response.status!==304){if(!response.ok)throw new Error('Сервер временно недоступен');state=await response.json();stateTag=response.headers.get('ETag')||'';}
  if(!state)return;
  refreshFailed=false;$('errorBanner').hidden=true;$('connection').innerHTML='<i></i>Сервер доступен';
  if(!dirty){
   const current=state.leads.find(l=>l.id===selected);
   if(privateWorkspace&&filter==='approved'&&current?.bucket==='sent')filter='sent';
   if(!visibleLeads().some(l=>l.id===selected)){selected=visibleLeads()[0]?.id||null;lastDetailVersion='';if(!selected)document.querySelector('.inbox-grid').classList.remove('show-detail');}
  }
  render();
 }catch(error){refreshFailed=true;$('errorBanner').hidden=false;$('connection').textContent='Нет связи';if(!state)$('leadList').innerHTML='<div class="empty-state"><strong>Не удалось загрузить заявки</strong>Проверьте соединение и повторите попытку. Данные не удалены.</div>';}
 finally{refreshing=false;if(refreshAgain){refreshAgain=false;queueMicrotask(refresh);}}
}
async function poll(){if(document.hidden){setTimeout(poll,15000);return}await refresh();const active=state?.leads.some(l=>['queued','processing','retry'].includes(l.status)||['queued','sending','retry'].includes(l.email_delivery?.status));setTimeout(poll,refreshFailed?30000:active?5000:15000);}

function render(){
 if(!state)return;
 $('navCount').textContent=state.workspace?state.stats.pending:state.stats.review;
 $('navCount').title=state.workspace?'Заявки без подтверждённой отправки ответа':'Заявки на проверке';
 for(const [id,key] of [['statTotal','total'],['statReview','review'],['approvedCount','approved'],['sentCount','sent'],['statDuplicates','duplicates'],['statSla','sla']])$(id).textContent=state.stats[key];
 document.querySelectorAll('[data-count]').forEach(el=>el.textContent=state.stats[el.dataset.count]);
 $('sentSummary').hidden=!state.workspace;$('sentTab').hidden=!state.workspace;
 $('approvedCaption').textContent=state.workspace?'в отправке':'согласовано';$('approvedTabCaption').textContent=state.workspace?'Отправка':'Согласованы';
 $('queueIssues').textContent=(state.stats.errors?`Ошибки обработки или ответа: ${state.stats.errors}. `:'')+(state.stats.notification_errors?`Проблемы уведомлений: ${state.stats.notification_errors}. Откройте карточку.`:'');
 $('actionsCaption').textContent=`${state.stats.actions} действий выполнено автоматически`;
 $('engineBadge').textContent=state.mode==='llm'?'AI-разбор настроен':'Разбор по правилам';
 document.querySelectorAll('[data-filter]').forEach(el=>{el.classList.toggle('selected',el.dataset.filter===filter);el.setAttribute('aria-pressed',String(el.dataset.filter===filter))});
 if(state.workspace){
  document.querySelector('.demo-badge').textContent='World of Vibecraft · закрытый кабинет';
  document.querySelector('.bottom-caption > span').textContent='Рабочие заявки · доступ владельца';
  document.querySelector('.modal-intro').textContent='Добавьте сообщение вручную. Проверьте данные и текст перед согласованием. Отправка email запускается отдельно.';
  $('fillExample').hidden=true;$('welcome').hidden=true;
 }
 configureWorkflow();
 if(view==='inbox'){renderList();renderDetail()}
 if(view==='crm')renderCrm();if(view==='audit')renderAudit();
}
function configureWorkflow(){
 const live=state.workspace;
 $('workflowIntro').textContent=live?'Форма World of Vibecraft сохраняет заявку в закрытом кабинете. Уведомление владельцу и ответ клиенту — две отдельные отправки.':'Познакомьтесь с процессом на вымышленных данных. Публичный стенд хранит отдельную базу и не отправляет письма.';
 $('workflowState').textContent=live?'Рабочая область':'Демонстрация';
 $('flowIntakeTitle').textContent=live?'Форма сайта':'Добавьте сообщение';
 $('flowIntakeText').textContent=live?'Сначала заявка сохраняется. Уведомление владельцу попадает в постоянную очередь и отправляется по email.':'Вставьте вымышленное сообщение. Исходный текст сохранится до начала разбора.';
 $('flowParseText').textContent=live?'AI или правила определяют суть запроса. Контакт берётся из формы, бюджет — из текста. Создаются сделка и шаблон ответа.':'AI или правила выделяют суть запроса; код извлекает контакт и бюджет из текста. Создаются сделка и шаблон ответа.';
 $('flowSendTitle').textContent=live?'Отправьте email':'Скопируйте текст';
 $('flowSendText').textContent=live?'Нажмите «Отправить по email» в согласованной карточке. Статус изменится после подтверждения Google.':'Согласованный ответ можно скопировать. Публичный стенд не отправляет сообщения.';
 $('flowApprovedLabel').textContent=live?'Отправка':'Согласованы';
 $('flowApprovedText').textContent=live?'Согласованные ответы без подтверждённой отправки: ещё не отправлены, стоят в очереди или требуют проверки ошибки.':'Ответы, проверенные менеджером. Отправки в демо нет.';
 $('flowSentLabel').hidden=!live;$('flowSentDefinition').hidden=!live;
 $('flowChannels').textContent=live?'Подключены форма WOV, email-уведомления владельцу и отправка подтверждённых ответов. Ящик Gmail не читается. Заявку также можно добавить вручную.':'Работают ручной ввод и демонстрационный API. Реальная форма сайта подключена к отдельной закрытой рабочей области.';
 $('flowMail').textContent=live?'Ответы клиентов на письма поступают в Gmail. Обратной синхронизации переписки в BriefOps пока нет. Telegram-контакт можно сохранить, но автоматической отправки в Telegram нет.':'Почтовые и Telegram-контакты в примерах вымышлены. Живые каналы к демонстрационной базе не подключены.';
 $('flowDelivery').textContent=live?'При сетевом сбое повторяется запрос с тем же ID. Отклонённую отправку можно повторить вручную. При неопределённом результате автоповтор остановлен: сначала проверьте доставку.':'Сценарии ниже показывают разбор, точный повтор обращения и восстановление после тестового сбоя.';
 $('flowDeadline').textContent=live?'Через 20 минут без подтверждённой отправки email заявка требует внимания. Это внутренний ориентир, не обещанный клиенту срок. На засыпающем сервере проверка выполняется после пробуждения.':'В демо контроль очереди заканчивается после согласования. Ориентир 20 минут помогает находить забытые заявки и не является обещанным сроком ответа.';
 $('flowPrivacy').textContent=live?'Рабочие заявки хранятся в отдельной базе. API проверяет вход владельца и подтверждённый email. Публичное демо не получает эти данные.':'Демонстрация общая: используйте только вымышленные данные. Рабочая область имеет отдельную базу и вход владельца.';
 $('llmNote').textContent=live?(state.email_enabled?'Email-отправка настроена. Результат каждого письма показан в карточке и истории.':'Email-отправка не настроена. Заявки и согласованные ответы сохраняются; письма пока не отправляются.'):'Публичное демо работает на общей базе примеров. Живую форму и отправку email смотрите в закрытом кабинете.';
 document.querySelector('.scenario-grid').hidden=live;
}

function go(next){if(dirty&&!confirm('Есть несохранённые изменения. Перейти без сохранения?'))return;dirty=false;editing=false;view=next;document.querySelectorAll('.page').forEach(el=>el.hidden=el.id!==`page-${next}`);document.querySelectorAll('.nav-item').forEach(el=>{el.classList.toggle('active',el.dataset.view===next);el.setAttribute('aria-current',el.dataset.view===next?'page':'false')});$('crumb').textContent={inbox:'Заявки',crm:'Доска сделок',workflow:'Как это работает',audit:'История действий'}[next];lastDetailVersion='';render();window.scrollTo({top:0,behavior:'smooth'})}
function pick(id){
 if(dirty&&id!==selected&&!confirm('В карточке есть несохранённые изменения. Открыть другую заявку?'))return;
 dirty=false;editing=false;selected=id;const target=state.leads.find(l=>l.id===id);if(target&&!visibleLeads().some(l=>l.id===id)){filter=target.bucket==='duplicate'?'all':target.bucket;query='';$('search').value='';}detailTab='review';lastDetailVersion='';
 if(view!=='inbox')go('inbox');else render();
 document.querySelector('.inbox-grid').classList.add('show-detail');
 if(innerWidth<=760)$('detail').scrollIntoView({behavior:'smooth',block:'start'});
}
function needsAttention(l){return ['needs_info','retry','failed'].includes(l.status)||l.analysis.below_floor||l.possible_duplicate||l.tasks.some(t=>t.kind==='sla'&&!t.done)}
function renderList(){
 const leads=visibleLeads();$('listCount').textContent=leads.length;
 $('listScope').textContent=query?`Найдено: ${leads.length}. Сводка выше относится ко всем заявкам.`:`Показано: ${leads.length}. Повторы доступны во вкладке «Все».`;
 $('leadList').innerHTML=leads.length?leads.map(l=>{
  const a=l.analysis,service=state.services[a.service||'unknown'],title=a.company||l.company||a.name||l.name||'Новая заявка';
  return `<button class="lead-row ${l.id===selected?'selected':''}" data-lead="${l.id}" aria-label="${esc(title)} — ${esc(labels[displayStatus(l)])}" aria-pressed="${l.id===selected}"><span class="company-avatar ${service.color}">${esc(title.slice(0,2).toUpperCase())}</span><span class="lead-row-body"><span class="row-heading"><span class="client-company">${esc(title)}</span><span class="row-time">${timeAgo(l.created_at)}</span></span><span class="row-summary">${esc(displaySummary(l))}</span><span class="row-footer">${badge(displayStatus(l))}<span class="row-price">${a.budget?money(a.budget):'Бюджет не указан'}</span></span></span></button>`;
 }).join(''):`<div class="empty-state"><strong>${query?'Ничего не найдено':filter==='review'?'Нет заявок на проверке':filter==='approved'?'Нет согласованных ответов в этой очереди':filter==='sent'?'Отправленных ответов пока нет':'Заявок пока нет'}</strong>${query?'Измените поиск или выберите другую вкладку.':'Новые обращения появятся здесь после сохранения.'}<button class="button secondary" id="emptyAction">Показать все заявки</button></div>`;
 $('emptyAction')?.addEventListener('click',()=>{query='';$('search').value='';changeFilter('all')});
}

function detailFields(a){const service=state.services[a.service||'unknown'];return `<div class="fields"><div><div class="field-label">Услуга</div><div class="field-value">${esc(service.label)}</div></div><div><div class="field-label">Бюджет клиента</div><div class="field-value big">${a.budget?money(a.budget):'Не указан'}</div></div><div><div class="field-label">Контакт</div><div class="field-value">${esc(a.contact||'Нужно уточнить')}</div></div><div><div class="field-label">Ответственный</div><div class="field-value"><span class="avatar">${service.initials}</span>${service.owner}</div></div></div>`}
function editFields(a){return `<div class="edit-fields"><label>Имя<input name="name" form="reviewForm" value="${esc(a.name)}" maxlength="80"></label><label>Компания<input name="company" form="reviewForm" value="${esc(a.company)}" maxlength="120"></label><label class="wide">Контакт<input name="contact" maxlength="254" form="reviewForm" value="${esc(a.contact)}" placeholder="Email, телефон или @telegram"></label><label>Услуга<select name="service" form="reviewForm">${Object.entries(state.services).map(([key,s])=>`<option value="${key}" ${a.service===key?'selected':''}>${esc(s.label)}</option>`).join('')}</select></label><label>Бюджет, ₽<input name="budget" form="reviewForm" type="number" min="1" max="100000000" step="1" value="${a.budget||''}"></label></div>`}
function timeline(events){return `<div class="timeline">${events.map(e=>`<div class="timeline-item"><span class="timeline-dot ${['sla','retry','failed','fallback'].includes(e.kind)?'warn':''}">${['sla','retry','failed'].includes(e.kind)?'!':'✓'}</span><div><div class="timeline-title">${esc(e.title)}</div><div class="timeline-detail">${esc(e.detail)}</div><div class="timeline-time">${clock(e.created_at)}</div></div></div>`).join('')}</div>`}
function renderDetail(){
 const lead=state.leads.find(l=>l.id===selected);
 if(!lead){$('detail').innerHTML='<div class="empty-state"><strong>Выберите заявку</strong>Здесь появятся данные клиента и черновик ответа.</div>';return}
 const version=[Math.floor(Date.now()/60000),lead.id,lead.updated_at,lead.status,lead.events.length,lead.email_delivery?.status,state.email_enabled,detailTab,editing].join(':');
 if(dirty||lastDetailVersion===version)return;lastDetailVersion=version;displayedVersion=lead.updated_at;
 const a=lead.analysis,title=a.company||lead.company||a.name||lead.name||'Новая заявка',done=lead.status==='approved',working=['queued','processing','retry','failed'].includes(lead.status);
 let body='';
 if(detailTab==='source')body=`<div class="source-meta"><span>${esc(sources[lead.source])}</span><span>${clock(lead.created_at)}</span></div><div class="source-message">${esc(lead.text)}</div><p class="draft-hint">Исходное сообщение сохраняется без изменений. Чтобы уточнить данные, вернитесь в «Заявка и ответ».</p>`;
 else if(detailTab==='history')body=timeline(lead.events);
 else if(lead.status==='duplicate')body=`<div class="state-panel"><span class="badge duplicate">Повтор обращения</span><h3>Эта заявка уже в работе</h3><p>Такое сообщение от этого клиента уже есть в системе. Вторую сделку и черновик не создавали.</p><button class="button primary" data-lead="${lead.duplicate_of}">Открыть исходную заявку →</button></div>`;
 else if(working)body=`<div class="state-panel">${lead.status==='failed'?'<div class="warning-box red">Обработка остановилась после трёх попыток. Заявка сохранена.</div>':`<div class="processing-state"><span class="spinner"></span>${lead.status==='retry'?'Повторяем обработку':'Обрабатываем заявку'}</div>`}<h3>${lead.status==='failed'?'Запустите обработку ещё раз':'Вы ничего не потеряете'}</h3><p>${lead.status==='failed'?'Откройте историю, проверьте причину и повторите обработку.':'Сообщение уже сохранено. Здесь появятся данные клиента и готовый черновик.'}</p>${['retry','failed'].includes(lead.status)?'<button class="button secondary" id="retryLead">Повторить сейчас</button>':''}</div>${timeline(lead.events)}`;
 else{
  const missing=a.missing||[];
  const prompt=done?(state.workspace?['Ответ согласован',lead.email_delivery?.status==='sent'?'Google подтвердил отправку. Это не подтверждение получения или прочтения.':lead.email_delivery?.status==='uncertain'?'Результат отправки неизвестен. Сначала проверьте письмо в Gmail; повторная отправка остановлена.':lead.email_delivery?.status==='failed'?'Отправка отклонена. Причина и действие для повтора показаны ниже.':['queued','sending','retry'].includes(lead.email_delivery?.status)?'Отправка в работе. Дождитесь результата в блоке email.':'Проверьте адрес и нажмите «Отправить по email» ниже.']:['Ответ готов','Скопируйте текст и отправьте клиенту удобным способом. Внешняя отправка здесь не выполняется.']):missing.length?['Уточните данные перед ответом',`Не хватает: ${missing.join(', ')}. Добавьте известные данные или оставьте вопросы в черновике.`]:['Проверьте данные и согласуйте ответ','Убедитесь, что контакт и бюджет указаны верно. Текст ответа можно отредактировать.'];
  let warnings='';
  if(a.below_floor&&!done)warnings+=`<div class="warning-box">${icon('info')}<span>Бюджет ниже стартового ориентира услуги. Уточните объём работ — в черновике уже есть пояснение.</span></div>`;
  if(lead.possible_duplicate&&!done)warnings+=`<div class="warning-box">${icon('copy')}<span>От этого клиента уже есть похожее обращение. <button class="text-link" data-lead="${lead.possible_duplicate}">Посмотреть заявку</button></span></div>`;
  if(lead.overdue)warnings+=`<div class="warning-box">${icon('clock')}<span>Клиент ждёт больше 20 минут. Проверьте и подготовьте ответ.</span></div>`;
  const next=state.leads.find(l=>pending(l)&&l.id!==lead.id);
  body=`<div class="next-action ${done?'success':missing.length?'warning':''}">${icon(done?'check-circle':'info')}<div><strong>${prompt[0]}</strong><p>${esc(prompt[1])}</p></div></div><div class="detail-section-label">1. Данные заявки${!done?`<button class="subtle-link" id="editFields">${icon('edit')}${editing?'Закрыть редактирование':'Изменить данные'}</button>`:''}</div>${editing?editFields(a):detailFields(a)}<div class="summary-note"><strong>ЗАДАЧА КЛИЕНТА</strong>${esc(displaySummary(lead))}</div>${warnings}<form id="reviewForm"><div class="detail-section-label draft-label"><label for="draft">2. Ответ клиенту</label><span class="mini-tag">${done?'СОГЛАСОВАН':'ЧЕРНОВИК'}</span></div><textarea id="draft" name="draft" class="draft-text" maxlength="5000" aria-label="Ответ клиенту" ${done?'readonly':''}>${esc(lead.draft)}</textarea><div class="draft-hint">${done?(state.workspace?'Текст согласован и сохранён. Отправка — отдельной кнопкой ниже.':'Текст сохранён. Отправьте его клиенту самостоятельно.'):'Согласование сохранит проверенный текст. Отправка выполняется отдельным действием.'}</div><div class="save-message" id="saveMessage" role="status">${!done&&!a.contact?'Для согласования добавьте контакт через «Изменить данные».':''}</div><div class="detail-actions">${done?`${state.workspace&&!lead.email_delivery?'<button class="button secondary" type="button" id="reopenLead">Вернуть в черновик</button>':''}${next?`<button type="button" class="button secondary" data-lead="${next.id}">Следующая заявка →</button>`:''}<button class="button primary" type="button" id="copyDraft">${icon('copy')}Скопировать ответ</button>`:`<button class="button secondary" type="submit">Сохранить изменения</button><button class="button primary" type="button" id="approveLead" ${!a.contact?'disabled':''}>${icon('check')}Согласовать ответ</button>`}</div></form><details class="analysis-details"><summary>Как обработана заявка</summary><p>${a.engine==='llm'?`AI-разбор: ${esc(a.model)} · ${esc(a.latency_ms)} мс.`:'Данные извлечены автоматически по правилам.'} Контакт и бюджет проверяются кодом. Черновик составляется по шаблону. Откройте «Историю», чтобы увидеть все действия.</p></details>`;
  if(state.workspace){if(done)body+=emailPanel(lead);body+=notificationPanel(lead);}
 }
 const progress=`<ol class="review-progress" aria-label="Этапы обработки"><li class="done"><i>✓</i>Принята</li><li class="${working?'current':'done'}"><i>${working?'2':'✓'}</i>${working?'Обработка':'Данные готовы'}</li><li class="${done?'done':!working?'current':''}"><i>${done?'✓':'3'}</i>${lead.bucket==='sent'?'Отправлено':done?'Согласовано':'Ваша проверка'}</li></ol>`;
 $('detail').innerHTML=`<div class="detail-header"><button class="mobile-back" id="backToList">← К списку заявок</button><div class="detail-eyebrow"><span>ЗАЯВКА #${lead.id.slice(0,6).toUpperCase()}</span>${badge(displayStatus(lead))}</div><h2 class="detail-title">${esc(title)}${a.urgent?'<span class="badge needs_info">Срочно</span>':''}</h2><div class="detail-subtitle">${esc(a.name||lead.name||'Новый контакт')} · ${esc(sources[lead.source])} · ${timeAgo(lead.created_at)}</div>${progress}</div><div class="detail-tabs"><button data-detail-tab="review" class="${detailTab==='review'?'selected':''}" aria-pressed="${detailTab==='review'}">Заявка и ответ</button><button data-detail-tab="source" class="${detailTab==='source'?'selected':''}" aria-pressed="${detailTab==='source'}">Исходное сообщение</button><button data-detail-tab="history" class="${detailTab==='history'?'selected':''}" aria-pressed="${detailTab==='history'}">История ${lead.events.length}</button></div><div class="detail-body">${body}</div>`;
 $('sendEmail')?.addEventListener('click',()=>sendEmail(lead));
 $('retryNotification')?.addEventListener('click',()=>retryNotification(lead));
 $('reopenLead')?.addEventListener('click',async()=>{try{await post('/api/leads/'+lead.id+'/reopen');filter='review';lastDetailVersion='';await refresh();notify('Ответ снова в черновике. Отправка не запускалась.')}catch(error){notify(error.message,true)}});
 bindDetail();
 $('backToList').onclick=()=>{if(dirty&&!confirm('Есть несохранённые изменения. Вернуться к списку?'))return;dirty=false;document.querySelector('.inbox-grid').classList.remove('show-detail');document.querySelector('.inbox-card').scrollIntoView({behavior:'smooth',block:'start'})};
 const form=$('reviewForm');
 if(form&&!done)document.querySelectorAll('#detail input,#detail select,#detail textarea').forEach(control=>control.addEventListener('input',()=>{dirty=true;$('saveMessage').textContent='Есть несохранённые изменения';const contact=new FormData(form).get('contact')??a.contact;const approve=$('approveLead');if(approve)approve.disabled=!String(contact||'').trim()||!$('draft').value.trim()}));
}
function bindDetail(){document.querySelectorAll('[data-detail-tab]').forEach(el=>el.onclick=()=>{if(dirty&&!confirm('Перейти во вкладку без сохранения изменений? Нажмите «Отмена», чтобы остаться в редакторе.'))return;dirty=false;detailTab=el.dataset.detailTab;lastDetailVersion='';renderDetail()});const form=$('reviewForm');if(form){form.addEventListener('input',()=>{dirty=true;$('saveMessage').textContent='Есть несохранённые изменения'});form.addEventListener('submit',async e=>{e.preventDefault();await saveReview(false)});$('approveLead')?.addEventListener('click',()=>saveReview(true))}$('editFields')?.addEventListener('click',()=>{if(dirty){notify('Сначала сохраните текст ответа');return}editing=!editing;lastDetailVersion='';renderDetail()});$('retryLead')?.addEventListener('click',async()=>{try{await post(`/api/leads/${selected}/retry`);notify('Заявка возвращена в очередь');await refresh()}catch(e){notify(e.message,true)}});$('copyDraft')?.addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('draft').value);notify('Ответ скопирован')}catch{notify('Выделите текст и скопируйте его вручную',true)}})}
async function saveReview(approve){if(busy)return;busy=true;const buttons=$('reviewForm').querySelectorAll('button');buttons.forEach(b=>b.disabled=true);try{const payload={...Object.fromEntries(new FormData($('reviewForm'))),version:displayedVersion};await post(`/api/leads/${selected}/${approve?'approve':'review'}`,payload);dirty=false;editing=false;if(approve){filter='approved';query='';$('search').value='';}lastDetailVersion='';notify(approve?(state.workspace?'Ответ согласован. Проверьте адрес и отправьте письмо отдельной кнопкой.':'Ответ готов. Его можно скопировать и отправить клиенту.'):'Изменения сохранены');await refresh()}catch(e){notify(e.message,true)}finally{busy=false;buttons.forEach(b=>b.disabled=false)}}
function renderCrm(){const columns=[['new','Ждут проверки'],['needs_info','Нужно уточнить'],['response_ready','Согласованы'],...(state.workspace?[['response_sent','Отправлено']]:[])];$('crmBoard').innerHTML=columns.map(([key,label])=>{const deals=state.deals.filter(d=>{const l=state.leads.find(l=>l.id===d.lead_id);if(l?.bucket==='sent')return key==='response_sent';return key==='needs_info'?l?.status==='needs_info':key==='new'?d.stage==='new'&&l?.status!=='needs_info':d.stage===key});return `<section class="kanban-column"><div class="kanban-heading">${label}<span>${deals.length}</span></div>${deals.map(d=>{const l=state.leads.find(l=>l.id===d.lead_id),s=state.services[l.analysis.service];return `<button class="deal-card" data-lead="${l.id}"><span class="badge neutral">${esc(s.label)}</span><h3>${esc(l.analysis.company||l.analysis.name)}</h3><p>${esc(l.analysis.name)} · ${esc(sources[l.source])}</p><div class="deal-card-foot"><strong>${d.value?money(d.value):'Бюджет уточняется'}</strong><span class="avatar">${s.initials}</span></div></button>`}).join('')||'<div class="empty-state">Нет сделок на этом этапе</div>'}</section>`}).join('')}
function renderAudit(){$('auditList').innerHTML=state.events.map(e=>{const lead=state.leads.find(l=>l.id===e.lead_id);return `<div class="audit-row"><span class="audit-date">${clock(e.created_at)}</span><div><h3>${esc(e.title)}</h3><p>${esc(e.detail)}</p></div><button data-lead="${esc(e.lead_id)}">${esc(lead?.company||lead?.analysis.name||e.lead_id?.slice(0,6)||'Заявка')} ↗</button></div>`}).join('')||'<div class="empty-state">Действия появятся после первой заявки</div>'}
const example={name:'Алина',company:'Mellow Studio',source:'website',text:'Здравствуйте! Хотим автоматизировать обработку заявок: форма сайта → CRM → уведомление менеджеру. Сейчас переносим данные вручную. Бюджет 160 тыс. рублей. Контакт: alina@example.com. Хотим начать в следующем месяце.'};
let demoNumber=0;
async function scenario(kind){if(busy)return;busy=true;document.querySelectorAll('.scenario').forEach(b=>b.disabled=true);try{let payload;if(kind==='duplicate'){const origin=state.leads.find(l=>l.status!=='duplicate'&&!['queued','processing','retry','failed'].includes(l.status));if(!origin)throw new Error('Сначала добавьте обычную заявку');payload={name:origin.name,company:origin.company,source:'n8n',text:origin.text}}else{demoNumber++;payload={name:'Никита',company:`Demo Lab ${Date.now().toString().slice(-4)}`,source:'n8n',text:`Нужна автоматизация сверки заявок с CRM. Бюджет 220 тыс. рублей. Контакт demo${Date.now()}@example.com. Сценарий ${demoNumber}.`,simulate_failure:kind==='failure'}}const result=await post('/api/intake',payload);filter='all';selected=result.lead.id;newLeadId=result.lead.id;document.querySelector('.inbox-grid').classList.add('show-detail');dirty=false;detailTab=kind==='failure'?'history':'review';lastDetailVersion='';go('inbox');notify(kind==='failure'?'Тестовый сбой включён: первая попытка не пройдёт, затем сработает повтор.':kind==='duplicate'?'Повтор передан в обработку. Проверьте, что второй сделки нет.':'Заявка передана роботу');await refresh()}catch(e){notify(e.message,true)}finally{busy=false;document.querySelectorAll('.scenario').forEach(b=>b.disabled=false)}}
document.addEventListener('click',e=>{const nav=e.target.closest('[data-view]');if(nav)go(nav.dataset.view);const lead=e.target.closest('[data-lead]');if(lead)pick(lead.dataset.lead);const fil=e.target.closest('[data-filter]');if(fil)changeFilter(fil.dataset.filter);const scen=e.target.closest('[data-scenario]');if(scen)scenario(scen.dataset.scenario)});
$('search').addEventListener('input',e=>{query=e.target.value.toLowerCase().trim();const matches=visibleLeads();if(!dirty&&!matches.some(l=>l.id===selected)){selected=matches[0]?.id||null;lastDetailVersion=''}renderList();renderDetail()});document.querySelectorAll('.new-lead').forEach(b=>b.onclick=()=>{$('formError').textContent='';$('newDialog').showModal()});document.querySelector('.close-dialog').onclick=()=>$('newDialog').close();$('fillExample').onclick=()=>{for(const [key,value]of Object.entries(example))$('newForm').elements[key].value=value};$('newForm').addEventListener('submit',async e=>{e.preventDefault();const button=e.target.querySelector('[type=submit]');button.disabled=true;$('formError').textContent='';try{const result=await post('/api/intake',Object.fromEntries(new FormData(e.target)));$('newDialog').close();e.target.reset();dirty=false;filter='review';selected=result.lead.id;newLeadId=result.lead.id;document.querySelector('.inbox-grid').classList.add('show-detail');detailTab='review';lastDetailVersion='';if(view!=='inbox')go('inbox');await refresh();notify('Заявка сохранена. Готовим данные и черновик ответа.')}catch(error){$('formError').textContent=error.message}finally{button.disabled=false}});$('sweep').onclick=async()=>{try{const result=await post('/api/sweep');notify(`Проверка завершена. Новых напоминаний: ${result.created}.`);await refresh()}catch(e){notify(e.message,true)}};window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue=''}});icons();refresh();setTimeout(poll,5000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh()});

function pending(l){return l.bucket==='review'}
function visibleLeads(){
 if(!state)return [];
 return state.leads.filter(l=>filter==='all'||l.bucket===filter).filter(l=>!query||[l.name,l.company,l.text,l.analysis.contact,l.analysis.name].join(' ').toLowerCase().includes(query)).sort((a,b)=>filter==='review'?(a.id===newLeadId?-1:rankLead(a))-(b.id===newLeadId?-1:rankLead(b))||a.created_at-b.created_at:filter==='approved'?deliveryRank(a)-deliveryRank(b)||a.created_at-b.created_at:b.created_at-a.created_at);
}

function deliveryRank(l){return ({uncertain:0,failed:1,retry:2,queued:3,sending:3})[l.email_delivery?.status]??4}
function rankLead(l){return l.status==='failed'?0:l.status==='retry'?1:l.status==='needs_info'?2:l.overdue?3:l.analysis.urgent?4:5}

function changeFilter(next){
 if(dirty&&!confirm('Есть несохранённые изменения. Изменить список?'))return;
 dirty=false;editing=false;filter=next;selected=visibleLeads()[0]?.id||null;lastDetailVersion='';render();
}
async function startExample(){
 if(busy||!state)return;busy=true;$('tryExample').disabled=true;
 try{
  const stamp=Date.now();const payload={...example,text:example.text.replace('alina@example.com',`demo${stamp}@example.com`)};
  const result=await post('/api/intake',payload);$('welcome').hidden=true;dirty=false;filter='review';selected=result.lead.id;newLeadId=result.lead.id;detailTab='review';lastDetailVersion='';go('inbox');document.querySelector('.inbox-grid').classList.add('show-detail');await refresh();
  if(innerWidth<=760)$('detail').scrollIntoView({behavior:'smooth',block:'start'});
  notify('Пример добавлен. Проверьте данные, затем согласуйте ответ.');
 }catch(e){notify(e.message,true)}finally{busy=false;$('tryExample').disabled=false}
}
$('tryExample').onclick=startExample;
$('dismissGuide').onclick=()=>{$('welcome').hidden=true;try{localStorage.setItem('briefops-guide-hidden','1')}catch{}};
$('showGuide').onclick=()=>{if(privateWorkspace){go('workflow');return}$('welcome').hidden=false;try{localStorage.removeItem('briefops-guide-hidden')}catch{};$('welcome').scrollIntoView({behavior:'smooth',block:'center'})};
try{$('welcome').hidden=localStorage.getItem('briefops-guide-hidden')==='1'}catch{}

function displaySummary(lead){return lead.analysis.summary||lead.text}
function displayStatus(lead){const d=lead.email_delivery?.status;return d==='sent'?'sent':['queued','sending','retry'].includes(d)?'sending':d==='failed'?'delivery_failed':d==='uncertain'?'delivery_uncertain':lead.status}

function emailPanel(lead){
 const d=lead.email_delivery,status=d?.status;
 const text={queued:'Письмо сохранено в очереди',sending:'Отправляем письмо',retry:'Повторяем запрос с тем же ID',sent:'Google подтвердил отправку. Получение и прочтение адресатом не проверяются.',uncertain:'Результат не подтверждён. Автоповтор остановлен. Сначала проверьте доставку в Gmail.',failed:'Письмо отклонено. Проверьте подключение и квоту Google; затем можно повторить ту же отправку.'}[status];
 const valid=/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(lead.analysis.contact||'');
 const sendButton=state.email_enabled&&valid&&(!status||status==='failed')?`<button type="button" class="button primary" id="sendEmail">${status==='failed'?'Повторить отправку':'Отправить по email'} →</button>`:'';
 return `<section class="email-panel"><h3>3. Отправка email</h3><p><strong>От:</strong> World of Vibecraft &lt;${esc(state.email_sender)}&gt;<br><strong>Кому:</strong> ${esc(d?.contact||lead.analysis.contact||'Email не указан')}<br><strong>Тема:</strong> ${esc(d?.subject||('World of Vibecraft — ответ на заявку '+lead.id))}</p><p role="status">${esc(text||(!valid?'В контакте указан Telegram или телефон. Для email нужен адрес клиента. Верните ответ в черновик, чтобы исправить контакт.':!state.email_enabled?'Отправка писем не настроена. Согласованный текст сохранён.':'Проверьте адрес и текст выше. Письмо уйдёт после нажатия кнопки.'))}</p>${sendButton}</section>`;
}
function notificationPanel(lead){const n=lead.email_notification;if(!['failed','uncertain'].includes(n?.status))return '';return `<div class="notification-note"><strong>Уведомление владельцу ${n.status==='failed'?'не отправлено':'не подтверждено'}</strong><br>Сама заявка сохранена. ${n.status==='failed'?'Проверьте квоту Google и повторите уведомление.':'Сначала проверьте доставку в Gmail. Автоповтор остановлен.'}${n.status==='failed'&&state.email_enabled?'<br><button class="button secondary" id="retryNotification">Повторить уведомление</button>':''}</div>`;}
async function retryNotification(lead){try{await post('/api/leads/'+lead.id+'/retry-notification');lastDetailVersion='';await refresh();notify('Повтор уведомления подтверждён')}catch(error){notify(error.message,true)}}

async function sendEmail(lead){
 const button=$('sendEmail');button.disabled=true;
 try{filter='approved';await post('/api/leads/'+lead.id+'/send-email');notify('Отправка подтверждена. Проверяем результат у Google.');lastDetailVersion='';await refresh();}
 catch(error){notify(error.message,true);button.disabled=false;}
}
if(privateWorkspace){
 $('workspaceLink').hidden=true;
 const link=document.createElement('button');link.className='text-link';link.textContent='Выйти';link.onclick=()=>window.briefopsAuth.signOut().catch(error=>notify(error.message,true));document.querySelector('.topbar-right').append(link);
 document.querySelectorAll('a[href="/api/export"]').forEach(link=>link.addEventListener('click',async event=>{
  event.preventDefault();try{const response=await apiFetch('/api/export');if(!response.ok)throw new Error('Не удалось выгрузить заявки');const url=URL.createObjectURL(await response.blob());const a=document.createElement('a');a.href=url;a.download='briefops-leads.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){notify(error.message,true);}
 }));
}
