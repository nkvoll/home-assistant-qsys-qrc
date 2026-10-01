/* Bundled Q-SYS panel: no external assets or browser dependencies. */
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const key = (name, mapping) => JSON.stringify(mapping.platform === 'media_player' ? [name, mapping.platform, mapping.settings.component || null] : [name, mapping.platform, mapping.settings.component || null, mapping.settings.control]);
const panelViews = new Set(['overview','browser','entities','monitor','diagnostics','import','export','migrate']);
const isPanelPath = path => path === '/qsys-qrc' || path.startsWith('/qsys-qrc/');
class QsysDiscardDialog extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});}
  set hass(value){this._hass=value;}
  showDialog(params){
    this.active=true;this.params=params;
    this.shadowRoot.innerHTML=`<ha-dialog header-title="Discard unsaved changes?"><p>Your changes haven’t been saved. Leaving this page will discard them.</p><ha-dialog-footer slot="footer"><ha-button slot="secondaryAction" data-keep>Keep editing</ha-button><ha-button slot="primaryAction" variant="danger" data-discard>Discard changes</ha-button></ha-dialog-footer></ha-dialog>`;
    const dialog=this.shadowRoot.querySelector('ha-dialog');dialog.open=true;
    this.shadowRoot.querySelector('[data-keep]').addEventListener('click',()=>this.closeDialog());
    this.shadowRoot.querySelector('[data-discard]').addEventListener('click',()=>{this.params.confirm();this.params=null;this.closeDialog();});
    dialog.addEventListener('closed',()=>this.finish());
  }
  closeDialog(){this.shadowRoot.querySelector('ha-dialog').open=false;this.finish();return true;}
  finish(){if(!this.active)return;this.active=false;this.params?.cancel();this.params=null;this.dispatchEvent(new CustomEvent('dialog-closed',{detail:{dialog:this.localName},bubbles:true,composed:true}));}
}
customElements.define('qsys-discard-dialog',QsysDiscardDialog);
class QsysPanel extends HTMLElement {
  constructor() {
    super(); this.attachShadow({mode:'open'}); this.view='overview'; this.cores=[]; this.controls=[]; this.selectedComponents=new Set(); this.componentErrors={}; this.inventory=[]; this.selected=new Set(); this.filter=''; this.frames=[]; this.paused=false;this.cleanControls=new Map();this.collator=new Intl.Collator(undefined,{numeric:true,sensitivity:'base'});this.controlSort={field:'name',direction:1};this.entitySort={field:'name',direction:1};
    this.shadowRoot.addEventListener('click', e => { const button=e.target.closest('[data-action]'); if(button) this.run(()=>this.action(button.dataset.action,button.dataset)); });
    this.shadowRoot.addEventListener('change', e => {if(e.target.id==='direction'){this.direction=e.target.value;this.updateMonitor();return;}if(e.target.matches('#core,#single-column,[data-component],[data-select],#all,[data-platform],[data-position],#file,#effective,#edit-field,#collision,#transfer'))this.run(()=>this.change(e.target));});
    this.shadowRoot.addEventListener('input', e => {if(e.target.id==='component-filter'){this.componentFilter=e.target.value;this.filterComponentChoices();} if(e.target.id==='monitor-search'){this.monitorSearch=e.target.value;this.updateMonitor();}if(e.target.id==='search') { this.filter=e.target.value; this.filterRows(); } });
  }
  set hass(value) { this._hass=value;this.updateEntityIcons(); if(!this.started && this.isConnected) {this.started=true; this.run(()=>this.initialize());} }
  hasUnsaved(){
    this.captureForm();
    if(this.review?.changes.some(change=>change.action!=='skip'))return true;
    if(this.view==='browser')return this.selected.size>0||this.controls.some(c=>JSON.stringify(this.controlSettings(c))!==this.cleanControls.get(this.controlKey(c)));
    if(this.view==='entities')return String(this.editValue??'')!==String(this.cleanEditValue??'');
    if(this.view==='import')return (this.document||'')!==(this.cleanDocument||'');
    return false;
  }
  defaultEntityName(c){return c.component&&!c.mediaPlayer?`${c.component} / ${c.metadata.Name}`:c.mediaPlayer?c.component:c.metadata.Name;}
  controlSettings(c){return [c.entityName??this.defaultEntityName(c),c.chosen||this.defaultPlatform(c),!!c.usePosition];}
  async confirmLeave(){
    if(!this.hasUnsaved())return true;
    if(this.leavePrompt)return this.leavePrompt;
    this.leavePrompt=new Promise(resolve=>this.dispatchEvent(new CustomEvent('show-dialog',{detail:{dialogTag:customElements.get('dialog-box')?'dialog-box':'qsys-discard-dialog',dialogImport:()=>Promise.resolve(),addHistory:false,dialogParams:{title:'Discard unsaved changes?',text:'Your changes haven’t been saved. Leaving this page will discard them.',confirmation:true,destructive:true,confirmText:'Discard changes',dismissText:'Keep editing',confirm:()=>resolve(true),cancel:()=>resolve(false)}},bubbles:true,composed:true})));
    const discard=await this.leavePrompt;this.leavePrompt=null;if(discard){this.discardEdits();this.render();}return discard;
  }
  discardEdits(){this.review=null;this.selected.clear();this.editValue='';this.cleanEditValue='';this.resetEditBaseline=true;this.document=this.cleanDocument||'';for(const c of this.controls){const clean=this.cleanControls.get(this.controlKey(c));if(clean){const [name,platform,position]=JSON.parse(clean);c.entityName=name;c.chosen=platform;c.usePosition=position;}}}
  installLeaveGuard(){
    if(!Number.isInteger(history.state?.qsysRouteIndex))history.replaceState({...history.state,qsysRouteIndex:0},'',location.href);
    this.panelUrl=location.href;this.panelHistory=history.state;
    this.beforeUnload=event=>{if(this.hasUnsaved()){event.preventDefault();event.returnValue='';}};
    this.leaveClick=event=>{const link=event.composedPath().find(node=>node.tagName==='A');if(!link||link.target||link.hasAttribute('download')||event.button||event.ctrlKey||event.metaKey||event.shiftKey||!this.hasUnsaved())return;const target=new URL(link.href,location.href);if(target.href===location.href)return;event.preventDefault();event.stopImmediatePropagation();this.confirmLeave().then(discard=>{if(discard){if(target.origin===location.origin){history.pushState(null,'',target.href);window.dispatchEvent(new CustomEvent('location-changed'));}else location.assign(target.href);}});};
    this.leaveLocation=event=>{
      if(location.href===this.panelUrl){
        if(this.cancelledTraversal){event.stopImmediatePropagation();this.cancelledTraversal.restored=true;this.finishTraversal();return;}
        this.routeChanged();return;
      }
      if(!this.hasUnsaved()){this.panelUrl=location.href;this.panelHistory=history.state;this.routeChanged();return;}
      const target=location.href,state=history.state;event.stopImmediatePropagation();
      const delta=state?.qsysRouteIndex-this.panelHistory?.qsysRouteIndex;
      if(event.type==='popstate'&&isPanelPath(location.pathname)&&Number.isInteger(delta)&&delta!==0){
        this.cancelledTraversal={delta,restored:false};history.go(-delta);
        this.confirmLeave().then(discard=>{this.cancelledTraversal.discard=discard;this.finishTraversal();});return;
      }
      history.replaceState(this.panelHistory,'',this.panelUrl);
      this.confirmLeave().then(discard=>{if(discard){history.replaceState(state,'',target);this.panelUrl=target;this.panelHistory=state;window.dispatchEvent(new CustomEvent('location-changed'));}});
    };
    this.leaveTraverse=event=>{if(event.navigationType!=='traverse'||!event.cancelable||!event.canIntercept||event.destination.url===this.panelUrl||!this.hasUnsaved())return;event.preventDefault();this.confirmLeave().then(discard=>{if(discard)setTimeout(()=>window.navigation.traverseTo(event.destination.key),0);});};
    window.navigation?.addEventListener('navigate',this.leaveTraverse);
    window.addEventListener('beforeunload',this.beforeUnload);window.addEventListener('click',this.leaveClick,true);window.addEventListener('location-changed',this.leaveLocation,true);window.addEventListener('popstate',this.leaveLocation,true);
  }
  finishTraversal(){
    const pending=this.cancelledTraversal;
    if(!pending?.restored||pending.discard===undefined)return;
    this.cancelledTraversal=null;
    if(pending.discard)history.go(pending.delta);
  }
  connectedCallback() { this.installLeaveGuard(); if(this._hass&&!this.started){this.started=true;this.run(()=>this.initialize());} this.timer=setInterval(()=>{if(this.view==='monitor'&&!this.paused&&!this.busy)this.refreshMonitor();if(this.view==='browser'&&this.selectedComponents.size&&this.controls.length&&!this.busy&&!this.polling)this.pollValues();},1500); }
  disconnectedCallback(){ clearInterval(this.timer);this.entityEventGeneration=(this.entityEventGeneration||0)+1;this.entityEventsUnsubscribe?.();this.entityEventsUnsubscribe=null;this.pendingEntityInventory=null;this.started=false;window.navigation?.removeEventListener('navigate',this.leaveTraverse);window.removeEventListener('beforeunload',this.beforeUnload);window.removeEventListener('click',this.leaveClick,true);window.removeEventListener('location-changed',this.leaveLocation,true);window.removeEventListener('popstate',this.leaveLocation,true); }
  async api(operation,params={}) {return this._hass.callWS({type:'qsys_qrc/panel',operation,...(this.entry?{entry_id:this.entry}:{}),...params});}
  async run(fn){if(this.busy)return;this.actionFocus=this.shadowRoot.activeElement?.dataset.action;this.captureForm();this.busy=true;this.error='';this.shadowRoot.querySelectorAll('button,input,select,textarea').forEach(b=>b.disabled=true);try{await fn();}catch(e){this.error=e.message||String(e);}finally{this.busy=false;this.render();if(this.pendingRoute){this.pendingRoute=false;this.routeChanged();}this.refreshEntityInventory();}}
  async load(){const data=await this.api('overview');this.cores=data.cores;if(!this.cores.some(c=>c.entry_id===this.entry))this.entry=this.cores[0]?.entry_id;}
  readRoute(){
    const url=new URL(location.href),match=url.pathname.match(/^\/qsys-qrc\/cores\/([^/]+)\/([^/]+)\/?$/);
    let view=url.searchParams.get('view')||'overview',core=url.searchParams.get('core');
    if(match){
      try{core=decodeURIComponent(match[1]);view=decodeURIComponent(match[2]);}
      catch{core=null;view='overview';}
    }
    const selected=match?this.cores.find(c=>c.name===core)||this.cores.find(c=>c.entry_id===core):this.cores.find(c=>c.entry_id===core);
    return {view:panelViews.has(view)?view:'overview',entry:selected?.entry_id||this.cores[0]?.entry_id};
  }
  writeRoute(mode='push'){
    const url=new URL(location.href);
    url.pathname=this.core?`/qsys-qrc/cores/${encodeURIComponent(this.core.name)}/${this.view}`:'/qsys-qrc';
    url.searchParams.delete('view');url.searchParams.delete('core');
    if(url.href!==location.href){
      const index=(history.state?.qsysRouteIndex||0)+(mode==='replace'?0:1);
      history[mode==='replace'?'replaceState':'pushState']({...history.state,qsysRouteIndex:index},'',url);
    }
    this.panelUrl=location.href;this.panelHistory=history.state;
    window.dispatchEvent(new CustomEvent('location-changed'));
  }
  async subscribeEntityEvents(){
    const connection=this._hass?.connection;
    if(!connection?.subscribeEvents)return;
    const generation=this.entityEventGeneration=(this.entityEventGeneration||0)+1;
    const unsubscribe=await connection.subscribeEvents(event=>{
      if(!this.isConnected||event.data.entry_id!==this.entry)return;
      this.pendingEntityInventory=this.entry;this.refreshEntityInventory();
    },'qsys_qrc_entities_ready');
    if(!this.isConnected||generation!==this.entityEventGeneration)unsubscribe();
    else this.entityEventsUnsubscribe=unsubscribe;
  }
  refreshEntityInventory(){
    if(this.busy||!this.pendingEntityInventory)return;
    const entry=this.pendingEntityInventory;this.pendingEntityInventory=null;
    if(entry!==this.entry||!['browser','entities','migrate'].includes(this.view))return;
    this.run(async()=>{await this.loadInventory();if(entry===this.entry&&this.message==='Changes saved. The Core integration is reloading.')this.message='Changes saved. The Core integration has reloaded.';});
  }
  async initialize(){await this.subscribeEntityEvents();await this.load();const route=this.readRoute();await this.navigate(route.view,{entry:route.entry,history:'replace'});}
  routeChanged(){
    if(!isPanelPath(location.pathname)||!this.started)return;
    if(this.busy){this.pendingRoute=true;return;}
    const route=this.readRoute();
    if(route.view===this.view&&route.entry===this.entry)return;
    this.run(()=>this.navigate(route.view,{entry:route.entry,history:'replace'}));
  }
  get core(){return this.cores.find(c=>c.entry_id===this.entry);}
  async navigate(view,{entry=this.entry,history:historyMode='push'}={}){if(!panelViews.has(view)||!await this.confirmLeave())return;this.entry=entry;this.view=view;this.review=null;this.selected.clear();this.filter='';if(view==='overview'||view==='diagnostics')await this.load();if(this.entry){if(view==='browser') {await this.loadInventory();this.components=(await this.api('components')).components.sort((a,b)=>this.collator.compare(a.Name,b.Name));this.controls=[];this.selectedComponents.clear();this.componentErrors={};this.cleanControls.clear();}if(view==='entities'||view==='migrate')await this.loadInventory();if(view==='monitor')await this.pollMonitor();if(view==='export')await this.loadExport();}this.writeRoute(historyMode);}
  async loadExport(){this.exportDocument=null;this.exportDocument=(await this.api('export',{effective:!!this.effective})).document;}
  async copyExport(){
    if(!this.exportDocument)throw Error('Load the YAML export before copying');
    try {if(!navigator.clipboard?.writeText)throw Error('Clipboard API unavailable');await navigator.clipboard.writeText(this.exportDocument);}
    catch(error){
      const input=document.createElement('textarea');input.value=this.exportDocument;input.style.cssText='position:fixed;left:-10000px;top:0';document.body.append(input);
      try {input.select();if(!document.execCommand('copy'))throw Error('Unable to copy. Select and copy the YAML below.');}
      finally{input.remove();}
    }
    this.message='YAML copied to clipboard.';
  }
  async loadInventory(){const entry=this.entry,result=await this.api('inventory');if(entry!==this.entry)return;this.inventory=result.inventory;this.editChoices=result.edit_choices;}
  editableFields(){
    const labels={name:'Name',unit_of_measurement:'Unit of measurement',min:'Minimum',max:'Maximum',step:'Step',mode:'Mode',attribute:'Sensor attribute',device_class:'Device class',state_class:'State class',options:'Select options (one per line)',use_position:'Use position',position_lower_limit:'Position lower limit',position_upper_limit:'Position upper limit',change_template:'Change template',value_template:'Value template',pattern:'Text pattern'};
    const rows=this.selectedRows();
    return Object.entries(labels).filter(([field])=>!rows.length||rows.every(row=>Object.hasOwn(row.mapping.settings,field)));
  }
  editInput(){
    const field=this.editField||'name',value=this.editValue??'';
    const rows=this.selectedRows();const platforms=[...new Set(rows.map(row=>row.mapping.platform))];
    if(field==='use_position')return `<label><input id="edit-value" type="checkbox" ${value===true?'checked':''}> Use position</label>`;
    if(['min','max','step','position_lower_limit','position_upper_limit'].includes(field)){
      const integer=['min','max'].includes(field)&&platforms.includes('text');
      const position=field.startsWith('position_');
      return `<label class="edit-value-label">New value<input id="edit-value" type="number" step="${integer?'1':'any'}" ${integer||position?'min="0"':''} ${position?'max="1"':''} value="${escapeHTML(value)}"></label>`;
    }
    const byPlatform=this.editChoices?.[field];
    if(byPlatform){
      const lists=(platforms.length?platforms:Object.keys(byPlatform)).map(p=>byPlatform[p]||[]);
      const options=(lists[0]||[]).filter(v=>lists.every(list=>list.includes(v)));
      const nullable=field!=='mode'||platforms.every(p=>p==='text');
      return `<label class="edit-value-label">New value<select id="edit-value">${nullable?'<option value="">None</option>':''}${options.map(v=>`<option value="${escapeHTML(v)}" ${v===value?'selected':''}>${escapeHTML(v)}</option>`).join('')}</select></label>`;
    }
    if(['options','change_template','value_template'].includes(field))return `<label class="edit-value-label">New value<textarea id="edit-value" rows="${field==='options'?5:4}" spellcheck="false">${escapeHTML(value)}</textarea></label>`;
    return `<label class="edit-value-label">New value<input id="edit-value" type="text" value="${escapeHTML(value)}" ${field==='attribute'?'list="sensor-attributes"':''}></label>${field==='attribute'?'<datalist id="sensor-attributes"><option value="String"><option value="Value"><option value="Position"></datalist>':''}`;
  }
  matchingComponents(){const query=(this.componentFilter||'').toLowerCase();return (this.components||[]).filter(c=>(c.Name+' '+c.Type).toLowerCase().includes(query));}
  filterComponentChoices(){const visible=new Set(this.matchingComponents().map(c=>c.Name));this.shadowRoot.querySelectorAll('[data-component-choice]').forEach(label=>label.hidden=!visible.has(label.dataset.componentChoice));}
  controlKey(control){return JSON.stringify([control.component||null,control.mediaPlayer?'media_player':'control',control.metadata.Name]);}
  async refreshComponents(){
    const response=await this.api('components');
    this.components=response.components.sort((a,b)=>this.collator.compare(a.Name,b.Name));
    const available=new Set(this.components.map(c=>c.Name));
    await this.showComponents([...this.selectedComponents].filter(name=>available.has(name)));
  }
  async refreshControls(){
    await this.loadInventory();
    await this.showComponents([...this.selectedComponents],{refresh:true});
  }
  async showComponents(names,{refresh=false}={}){
    const previous=new Map(this.controls.map(c=>[this.controlKey(c),c]));
    const selected=new Set([...this.selected].map(i=>this.controlKey(this.controls[i])));
    const requested=new Set(names),loaded=new Set(this.controls.filter(c=>c.component).map(c=>c.component));
    const missing=names.filter(name=>refresh||!loaded.has(name)),results=new Map();
    const entry=this.entry;
    await Promise.all(Array.from({length:Math.min(4,missing.length)},async()=>{
      while(missing.length){const component=missing.shift();
        try {const response=await this.api('controls',{component});results.set(component,response.controls.map(c=>({...c,component})));delete this.componentErrors[component];}
        catch(error){this.componentErrors[component]=error.message||String(error);}
      }
    }));
    if(entry!==this.entry)return;
    this.selectedComponents=requested;
    const controls=[];
    for(const component of this.components||[])if(requested.has(component.Name)){
      controls.push(...(results.get(component.Name)||this.controls.filter(c=>c.component===component.Name&&!c.mediaPlayer)));
    }
    for(const component of this.components||[])if(requested.has(component.Name)&&!this.componentErrors[component.Name]&&['URL_receiver','audio_file_player','gain'].includes(component.Type)){
      controls.push({component:component.Name,mediaPlayer:true,metadata:{Name:'Component media player',Type:'Media player',Direction:'read/write'},platforms:['media_player'],suggestions:{media_player:{component:component.Name,name:component.Name}}});
    }
    controls.push(...this.controls.filter(c=>!c.component));
    this.controls=controls.map(c=>{
      const old=previous.get(this.controlKey(c));
      if(!old)return c;
      if(!refresh)return old;
      const updated={...c};
      for(const field of ['entityName','chosen','usePosition'])if(Object.hasOwn(old,field))updated[field]=old[field];
      return updated;
    });
    for(const c of this.controls)if(!this.cleanControls.has(this.controlKey(c)))this.cleanControls.set(this.controlKey(c),JSON.stringify(this.controlSettings(c)));
    this.selected=new Set(this.controls.flatMap((c,i)=>selected.has(this.controlKey(c))&&!this.mappedControl(c)?[i]:[]));
  }
  async pollValues(){
    this.polling=true;const entry=this.entry,controls=this.controls;
    const components=[...new Set(controls.map(c=>c.component).filter(Boolean))];
    try {
      await Promise.all(Array.from({length:Math.min(4,components.length)},async()=>{
        while(components.length){const component=components.shift();
          const names=controls.filter(c=>c.component===component&&!c.mediaPlayer).map(c=>c.metadata.Name);
          const result=await this.api('values',{component,names});
          if(entry!==this.entry||this.view!=='browser'||controls!==this.controls)return;
          result.controls.forEach(value=>{const i=this.controls.findIndex(c=>!c.mediaPlayer&&c.component===component&&c.metadata.Name===value.Name);if(i>=0){Object.assign(this.controls[i].metadata,value);const cell=this.shadowRoot.querySelector(`[data-value="${i}"]`);if(cell)cell.textContent=value.String??value.Value??'';}});
        }
      }));
    } catch(e){this.error=e.message||String(e);const status=this.shadowRoot.querySelector('#live-status');if(status)status.textContent='Live values unavailable: '+this.error;}
    finally{this.polling=false;}
  }
  async refreshMonitor(){
    if(this.monitorRefreshing)return;
    this.monitorRefreshing=true;const entry=this.entry,generation=this.monitorGeneration;
    try {
      const result=await this.api('monitor');
      if(!this.isConnected||this.view!=='monitor'||entry!==this.entry||generation!==this.monitorGeneration||this.busy||this.paused)return;
      this.capture=result.capture;this.frames=result.frames;
      this.updateMonitor(true);
      const error=this.shadowRoot.querySelector('#monitor-error');if(error){error.hidden=true;error.textContent='';}
    }catch(error){
      if(this.isConnected&&this.view==='monitor'&&entry===this.entry&&generation===this.monitorGeneration){const status=this.shadowRoot.querySelector('#monitor-error');if(status){status.textContent=error.message||String(error);status.hidden=false;}}
    }finally{this.monitorRefreshing=false;}
  }
  monitorRow(frame){return `<tr data-sequence="${frame.sequence}"><td>${escapeHTML(frame.timestamp)}</td><td>${frame.direction==='sent'?'→ Sent':'← Received'}</td><td>${escapeHTML(frame.id)}</td><td><details data-frame="${frame.sequence}"><summary>${escapeHTML(frame.method||(frame.payload.error?'Error':frame.id!==undefined?'Response':'Notification'))}</summary><pre>${escapeHTML(JSON.stringify(frame.payload,null,2))}</pre></details></td></tr>`;}
  updateMonitor(preserveScroll=false){
    const body=this.shadowRoot.querySelector('#monitor-rows');if(!body)return;
    const existing=new Map([...body.rows].map(row=>[row.dataset.sequence,row]));
    const viewportTop=this.getBoundingClientRect().top;
    const anchor=preserveScroll&&this.scrollTop>0?[...body.rows].find(row=>!row.hidden&&row.getBoundingClientRect().bottom>viewportTop):null;
    const anchorTop=anchor?.getBoundingClientRect().top;
    const retained=new Set(this.frames.map(frame=>String(frame.sequence)));
    for(const [sequence,row] of existing)if(!retained.has(sequence)){row.remove();existing.delete(sequence);}
    const fragment=document.createDocumentFragment();
    for(const frame of this.frames.slice().reverse()){
      const sequence=String(frame.sequence);let row=existing.get(sequence);
      if(!row){const template=document.createElement('template');template.innerHTML=this.monitorRow(frame);row=template.content.firstElementChild;fragment.append(row);}
      if(row.qsysSearchText===undefined){row.qsysSearchText=JSON.stringify(frame).toLowerCase();row.qsysDirection=frame.direction;}
      const hidden=!!this.direction&&row.qsysDirection!==this.direction||!row.qsysSearchText.includes((this.monitorSearch||'').toLowerCase());
      if(row.hidden!==hidden)row.hidden=hidden;
    }
    if(fragment.childNodes.length)body.prepend(fragment);
    const status=this.shadowRoot.querySelector('#monitor-status'),text=`${this.capture?'Capturing':'Capture stopped'} · ${this.frames.length}/500 frames retained.`;
    if(status&&status.textContent!==text)status.textContent=text;
    const capture=this.shadowRoot.querySelector('[data-action="capture"]'),label=this.capture?'Stop capture':'Start capture';
    if(capture&&capture.textContent!==label)capture.textContent=label;
    if(anchor?.isConnected&&!anchor.hidden)this.scrollTop+=anchor.getBoundingClientRect().top-anchorTop;
  }
  async pollMonitor(params={}){this.monitorGeneration=(this.monitorGeneration||0)+1;const result=await this.api('monitor',params);this.capture=result.capture;this.frames=result.frames;}
  async change(el){
    if(el.id==='single-column')this.singleColumn=el.checked;
    if(el.id==='core')await this.navigate(this.view,{entry:el.value});
    if(el.dataset.component!==undefined){const names=new Set(this.selectedComponents);el.checked?names.add(el.dataset.component):names.delete(el.dataset.component);await this.showComponents([...names]);}
    if(el.dataset.select!==undefined&&(this.view!=='browser'||!this.mappedControl(this.controls[Number(el.dataset.select)]))){el.checked?this.selected.add(Number(el.dataset.select)):this.selected.delete(Number(el.dataset.select));}
    if(el.id==='all'){this.shadowRoot.querySelectorAll('tbody tr').forEach(row=>{if(row.hidden)return;const c=row.querySelector('[data-select]');if(c&&(this.view==='browser'?!this.mappedControl(this.controls[Number(c.dataset.select)]):this.inventory[Number(c.dataset.select)]?.source===(this.view==='migrate'?'yaml':'ui'))){c.checked=el.checked;el.checked?this.selected.add(Number(c.dataset.select)):this.selected.delete(Number(c.dataset.select));}});}
    if(el.dataset.platform!==undefined){const index=Number(el.dataset.platform);this.controls[index].chosen=el.value;if(this.mappedControl(this.controls[index]))this.selected.delete(index);}
    if(el.dataset.position!==undefined)this.controls[Number(el.dataset.position)].usePosition=el.checked;
    if(el.id==='file'&&el.files[0]){if(el.files[0].size>262144)throw Error('YAML file exceeds 256 KiB');this.document=await el.files[0].text();}
    if(el.id==='edit-field'){this.editField=el.value;this.editValue='';this.resetEditBaseline=true;}
    if(el.id==='collision')this.collision=el.value;
    if(el.id==='transfer')this.transfer=el.checked;
    if(el.id==='effective'){this.effective=el.checked;if(this.view==='export')await this.loadExport();}
    if(el.id==='direction'||el.id==='monitor-search'){this.direction=this.shadowRoot.querySelector('#direction').value;this.monitorSearch=this.shadowRoot.querySelector('#monitor-search').value;}
  }
  filterRows(){const query=this.filter.toLowerCase();this.shadowRoot.querySelectorAll('tbody tr[data-search]').forEach(row=>row.hidden=!row.dataset.search.toLowerCase().includes(query));this.shadowRoot.querySelectorAll('[data-group]').forEach(group=>{const rows=[...this.shadowRoot.querySelectorAll('[data-control-group]')].filter(row=>row.dataset.controlGroup===group.dataset.group);group.hidden=!!query&&!rows.some(row=>!row.hidden);});}
  selectedRows(){return [...this.selected].map(i=>this.inventory[i]);}
  entityRows(migrate=false){
    if(migrate)return this.sortedRows(this.inventory,'entities').filter(({item})=>item.source==='yaml');
    const uiKeys=new Set(this.inventory.filter(row=>row.source==='ui').map(row=>key(this.core.name,row.mapping)));
    const yamlKeys=new Set(this.inventory.filter(row=>row.source==='yaml').map(row=>key(this.core.name,row.mapping)));
    const rows=this.inventory.map(row=>({...row,displaySource:row.source==='ui'&&yamlKeys.has(key(this.core.name,row.mapping))?'ui + yaml':row.source}));
    return this.sortedRows(rows,'entities').filter(({item})=>item.source!=='yaml'||!uiKeys.has(key(this.core.name,item.mapping)));
  }
  async preview(request){this.reviewReturnAction=this.actionFocus;this.pending=request;this.review=await this.api(request.operation,request);}
  sortedRows(items,kind){
    const sort=kind==='controls'?this.controlSort:this.entitySort;
    const value=item=>{
      if(kind==='controls'){
        const c=item,metadata=c.metadata;
        return {name:metadata.Name,type:(metadata.Type||'')+' '+(metadata.Direction||''),value:metadata.Value??metadata.String,
          platform:c.chosen||this.defaultPlatform(c),entityName:c.entityName??this.defaultEntityName(c)}[sort.field];
      }
      const settings=item.mapping.settings;
      return {name:item.entity_name||settings.name||settings.control||settings.component,platform:item.mapping.platform,
        target:(settings.component||'Named Control')+' / '+(settings.control||'media player'),source:item.displaySource||item.source,
        details:JSON.stringify(settings)}[sort.field];
    };
    return items.map((item,index)=>({item,index})).sort((a,b)=>{
      const left=value(a.item),right=value(b.item);
      const compared=typeof left==='number'&&typeof right==='number'?left-right:this.collator.compare(String(left??''),String(right??''));
      return sort.direction*compared||a.index-b.index;
    });
  }
  sortHeader(label,kind,field){
    const sort=kind==='controls'?this.controlSort:this.entitySort,active=sort.field===field;
    return `<th aria-sort="${active?(sort.direction===1?'ascending':'descending'):'none'}"><button class="sort-header" data-action="sort" data-kind="${kind}" data-field="${field}">${label}<ha-icon class="sort-icon ${active?'':'inactive'}" icon="mdi:sort-${active&&sort.direction===-1?'descending':'ascending'}" aria-hidden="true"></ha-icon></button></th>`;
  }
  async action(action,data){
    if(action==='sort'){const sort=data.kind==='controls'?this.controlSort:this.entitySort;sort.direction=sort.field===data.field?-sort.direction:1;sort.field=data.field;return;}
    if(action==='more-info'){this.dispatchEvent(new CustomEvent('hass-more-info',{detail:{entityId:data.entity},bubbles:true,composed:true}));return;}
    if(action==='core-settings'){if(!await this.confirmLeave())return;history.pushState(null,'','/config/integrations/integration/qsys_qrc');window.dispatchEvent(new CustomEvent('location-changed'));return;}
    if(action==='back'){if(!await this.confirmLeave())return;history.pushState(null,'','/config/connectivity');window.dispatchEvent(new CustomEvent('location-changed'));return;}
    if(action==='navigate')return this.navigate(data.view);
    if(action==='refresh')return this.view==='browser'?this.refreshControls():this.navigate(this.view);
    if(action==='refresh-components')return this.refreshComponents();
    if(action==='show-all-components')return this.showComponents([...new Set([...this.selectedComponents,...this.matchingComponents().map(c=>c.Name)])]);
    if(action==='clear-components')return this.showComponents([]);
    if(action==='retry-components'){const requested=[...this.selectedComponents];await this.showComponents(requested,{refresh:true});return;}
    if(action==='named'){const name=this.shadowRoot.querySelector('#named').value.trim();const response=await this.api('named',{name});if(!this.controls.some(c=>!c.component&&c.metadata.Name===name)){const c={...response.controls[0],component:null};this.controls.push(c);this.cleanControls.set(this.controlKey(c),JSON.stringify(this.controlSettings(c)));}}
    if(action==='create'){
      const mappings=[...this.selected].map(i=>{const c=this.controls[i],p=c.chosen||this.defaultPlatform(c);const settings={...c.suggestions[p],component:c.component};if(p==='number')settings.use_position=!!c.usePosition;settings.name=this.shadowRoot.querySelector(`[data-name="${i}"]`).value;return {platform:p,settings};});
      return this.preview({operation:'create',mappings,collision:'skip'});
    }
        if(action==='delete'||action==='edit'){
      const identities=this.selectedRows().map(r=>JSON.parse(key(this.core.name,r.mapping)));
      const request={operation:action,identities};
      if(action==='edit'){
        const field=this.editField||'name',input=this.shadowRoot.querySelector('#edit-value'),raw=input.value;
        let value=input.type==='checkbox'?input.checked:raw;
        if(input.type==='number'){value=input.valueAsNumber;if(!input.checkValidity()||!Number.isFinite(value))throw Error('Enter a valid number');}
        if(field==='options')value=raw.split('\n').filter(Boolean);
        if(input.tagName==='SELECT'&&!raw)value=null;
        request.patch={[field]:value};
      }
      return this.preview(request);
    }
    if(action==='copy-export')return this.copyExport();
    if(action==='export'){
      if(!this.exportDocument)throw Error('Load the YAML export before downloading');
      this.download(this.exportDocument,`${this.core.name}.yaml`,'application/yaml');
    }
    if(action==='import')return this.preview({operation:'import',document:this.shadowRoot.querySelector('#document').value,collision:this.shadowRoot.querySelector('#collision').value,transfer_yaml:this.shadowRoot.querySelector('#transfer').checked});
    if(action==='migrate')return this.preview({operation:'migrate',identities:this.selectedRows().map(r=>JSON.parse(key(this.core.name,r.mapping))),collision:this.shadowRoot.querySelector('#collision').value});
    if(action==='save'){await this.api(this.pending.operation,{...this.pending,commit:true,revision:this.review.revision,review_token:this.review.review_token});for(const i of this.selected)if(this.view==='browser')this.cleanControls.set(this.controlKey(this.controls[i]),JSON.stringify(this.controlSettings(this.controls[i])));if(this.view==='import')this.cleanDocument=this.document;this.editValue='';this.resetEditBaseline=true;this.review=null;this.message='Changes saved. The Core integration is reloading.';this.selected.clear();if(['browser','entities','migrate'].includes(this.view))await this.loadInventory();}
    if(action==='cancel'){this.review=null;}
    if(action==='capture')await this.pollMonitor({capture:!this.capture});
    if(action==='pause'){this.paused=!this.paused;this.monitorGeneration=(this.monitorGeneration||0)+1;}
    if(action==='clear')await this.pollMonitor({clear:true});
    if(action==='download-monitor')this.download(JSON.stringify(this.frames,null,2),'qrc-monitor.json','application/json');
  }
  download(text,name,type){const url=URL.createObjectURL(new Blob([text],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  defaultPlatform(control){return ['media_player','select','switch','number','text','binary_sensor','sensor'].find(p=>control.platforms.includes(p));}
  button(label,action,extra=''){return `<button data-action="${action}" ${extra}>${label}</button>`;}
  card(title,description,view){return `<button class="card" data-action="navigate" data-view="${view}"><h2>${title}</h2><p>${description}</p><span>Open →</span></button>`;}
  toolbar(){const label=['entities','migrate'].includes(this.view)?'Filter entities':'Filter controls';return `<div class="tools table-filter"><input id="search" placeholder="${label}…" aria-label="${label}" value="${escapeHTML(this.filter)}">${this.button('Refresh','refresh')}</div>`;}
  renderOverview(){return `<h2>Entities</h2><p>Add controls from your Q-SYS design, then manage their Home Assistant entities. No YAML is required.</p><div class="grid">${this.card('Add entities','Choose components or look up Named Controls, select controls, then review and create.','browser')}${this.card('Manage entities','Inspect, edit settings, or delete existing entities.','entities')}</div><h2>Cores</h2><p>Choose a Core in the header. Use Core settings to change its connection or polling, add another Core, or remove an integration entry.</p>${this.button('Core settings','core-settings')}<div class="grid">${this.cores.map(c=>`<article class="card"><h2>${escapeHTML(c.name)}</h2><span class="badge">${escapeHTML(c.status)}</span><p>${escapeHTML(c.engine.DesignName||'Unknown design')}</p><p>${c.entities} entity definitions · ${escapeHTML(c.engine.Platform||'Q-SYS Core')}</p></article>`).join('')}</div><h2>Import & migration</h2><p>Optional tools for existing YAML configurations and sharing entity definitions.</p><div class="grid">${this.card('Import YAML','Upload or paste portable entity definitions and review changes.','import')}${this.card('Export YAML','Download portable entity definitions for another installation.','export')}${this.card('Migrate from Home Assistant YAML','Move existing YAML entities to UI management.','migrate')}</div>`;}
  mappedControl(control){
    const platform=control.chosen||this.defaultPlatform(control);
    return this.inventory.find(row=>row.mapping.platform===platform&&(row.mapping.settings.component||null)===(control.component||null)&&(control.mediaPlayer||row.mapping.settings.control===control.metadata.Name));
  }
  renderControl(control,index){
    const c=control,i=index,component=c.component||'Named Controls',mapped=this.mappedControl(c);
    return `<tr class="${mapped?'mapped-row':''}" data-control-group="${escapeHTML(component)}" data-search="${escapeHTML(component+' '+JSON.stringify(c.metadata))}"><td><input type="checkbox" data-select="${i}" aria-label="Select ${escapeHTML(component+' / '+c.metadata.Name)}" ${this.selected.has(i)&&!mapped?'checked':''} ${mapped?'disabled':''}></td><td>${escapeHTML(c.metadata.Name)}${mapped?(mapped.entity_id?`<button class="mapped-badge mapped-link" data-action="more-info" data-entity="${escapeHTML(mapped.entity_id)}" aria-label="Already mapped: ${escapeHTML(mapped.entity_name||mapped.entity_id)}">Already mapped</button>`:'<span class="mapped-badge" title="The entity is being registered. Refresh to open its dialog.">Already mapped</span>'):''}</td><td>${escapeHTML(c.metadata.Type)}<br>${escapeHTML(c.metadata.Direction||'Direction unverified')}</td><td data-value="${i}">${c.mediaPlayer?'—':escapeHTML(c.metadata.String??c.metadata.Value)}</td><td>${c.mediaPlayer?'media_player':`<select data-platform="${i}" aria-label="Entity type for ${escapeHTML(component+' / '+c.metadata.Name)}">${c.platforms.map(p=>`<option ${p===(c.chosen||this.defaultPlatform(c))?'selected':''}>${p}</option>`).join('')}</select>`}${(c.chosen||this.defaultPlatform(c))==='number'?`<label><input type="checkbox" data-position="${i}" aria-label="Use position for ${escapeHTML(component+' / '+c.metadata.Name)}" ${c.usePosition?'checked':''} ${mapped?'disabled':''}> Use position</label>`:''}</td><td><input data-name="${i}" aria-label="Entity name for ${escapeHTML(component+' / '+c.metadata.Name)}" value="${escapeHTML(c.entityName??this.defaultEntityName(c))}" ${mapped?'disabled':''}></td></tr>`;
  }
  helpTooltip(id,label,text){
    return `<span class="help"><button type="button" class="help-icon" aria-label="About ${escapeHTML(label)}" aria-describedby="help-${id}">?</button><span class="help-tooltip" role="tooltip" id="help-${id}">${escapeHTML(text)}</span></span>`;
  }
  renderBrowser(){
    const sortedControls=this.sortedRows(this.controls,'controls');
    const groups=[...(this.components||[]).filter(c=>this.selectedComponents.has(c.Name)).map(c=>c.Name),...(this.controls.some(c=>!c.component)?['Named Controls']:[])];
    return `<p class="browser-guide">Select components or look up Named Controls, then use the table checkboxes to choose what to add. Set the entity types and names, click <strong>Review creation</strong>, and finish with <strong>Create</strong>.</p><section class="card browser-config-card"><div class="section-heading"><h2>1. Choose components</h2>${this.helpTooltip('components','Components','In Q-SYS Designer, check the component’s Properties: it must have a Code Name and Script Access set to External (or All) to appear here.')}</div><p>Choosing a component displays its controls below. It does not create entities. You can choose several components together.</p><div class="tools"><input id="component-filter" placeholder="Filter components…" aria-label="Filter components" value="${escapeHTML(this.componentFilter||'')}">${this.button('Refresh','refresh-components','aria-label="Refresh components"')}${this.button('Select all','show-all-components')}${this.button('Clear','clear-components')}<label><input id="single-column" type="checkbox" ${this.singleColumn?'checked':''}> Single column</label></div>${!(this.components||[]).length?'<p class="empty-state">No components found. In Q-SYS Designer, set a Code Name and Script Access to External or All, then refresh components.</p>':''}<div class="component-picker ${this.singleColumn?'single-column':''}">${(this.components||[]).map(c=>`<label data-component-choice="${escapeHTML(c.Name)}"><input type="checkbox" data-component="${escapeHTML(c.Name)}" ${this.selectedComponents.has(c.Name)?'checked':''}><span class="component-label"><span class="component-name">${escapeHTML(c.Name)}</span><span class="component-type">${escapeHTML(c.Type)}</span></span></label>`).join('')}</div></section><section class="card browser-config-card"><div class="section-heading"><h2>Or look up Named Controls</h2>${this.helpTooltip('named-controls','Named Controls','Named Controls are controls exposed by name in the Q-SYS Designer Named Controls panel. QRC addresses them directly by their exact name, but has no documented command to list them all. Enter a name from Designer to look it up; automatic discovery is unavailable.')}</div><p>Enter the exact name from Designer’s Named Controls panel. After lookup, select the control in the table below to create its entity.</p><div class="tools"><input id="named" placeholder="Exact top-level Named Control name" aria-label="Named Control name">${this.button('Look up control','named')}</div></section><h2>2. Choose controls to create entities</h2><p>Select the table checkboxes, choose entity types and names, then review your selection before creating.</p><p id="live-status">Component values refresh while this browser is open.</p><p>${this.selectedComponents.size} components shown · ${this.controls.filter(c=>!c.mediaPlayer).length} controls · ${this.selected.size} selected for creation. Select visible controls with the table checkbox; filtered-out selections stay in the batch.</p>${Object.keys(this.componentErrors).filter(name=>this.selectedComponents.has(name)).length?`<p class="error">${Object.entries(this.componentErrors).filter(([name])=>this.selectedComponents.has(name)).map(([name,error])=>escapeHTML(name+': '+error)).join('<br>')}</p>${this.button('Retry discovery','retry-components')}`:''}${this.toolbar()}${!this.controls.length?'<p class="empty-state">Choose a component above or look up a Named Control to see available controls here.</p>':''}<div class="table"><table><thead><tr><th><input id="all" type="checkbox" aria-label="Select visible controls"></th>${this.sortHeader('Control','controls','name')}${this.sortHeader('Type / direction','controls','type')}${this.sortHeader('Value','controls','value')}${this.sortHeader('Entity type','controls','platform')}${this.sortHeader('Entity name','controls','entityName')}</tr></thead><tbody>${groups.map(group=>{
      return `<tr class="component-group" data-group="${escapeHTML(group)}"><th colspan="6">${escapeHTML(group)}</th></tr>${sortedControls.map(({item:c,index:i})=>((c.component||'Named Controls')===group)?this.renderControl(c,i):'').join('')}`;
    }).join('')}</tbody></table></div><div class="action-bar" aria-label="Create entities"><span role="status">${this.selected.size} selected for creation</span>${this.button(`Review creation (${this.selected.size})`,'create',this.selected.size?'class="filled"':'disabled')}</div>`;
  }
  entityNameCell(row,index){
    const settings=row.mapping.settings;
    const content=`<ha-state-icon data-entity-icon="${index}" aria-hidden="true"></ha-state-icon><span>${escapeHTML(row.entity_name||settings.name||settings.control||settings.component)}</span>`;
    return row.entity_id?`<button class="entity-name entity-label" data-action="more-info" data-entity="${escapeHTML(row.entity_id)}">${content}</button>`:`<span class="entity-label">${content}</span>`;
  }
  updateEntityIcons(){
    this.shadowRoot.querySelectorAll('[data-entity-icon]').forEach(icon=>{
      const row=this.inventory[Number(icon.dataset.entityIcon)];if(!row)return;
      icon.stateObj=this._hass?.states[row.entity_id]||{entity_id:row.entity_id||`${row.mapping.platform}.qsys_preview`,state:'unavailable',attributes:{device_class:row.mapping.settings.device_class}};
    });
  }
  renderEntities(migrate=false){return `<p>${migrate?'Select definitions configured via Home Assistant YAML to transfer ownership to the UI. Remove transferred definitions from your YAML files afterward.':'Definitions configured via Home Assistant YAML are read-only until migrated. Deleting an imported mapping can reactivate its remaining definition configured via Home Assistant YAML.'}</p>${this.toolbar()}<div class="table"><table><thead><tr><th><input id="all" type="checkbox" aria-label="Select visible mappings"></th>${this.sortHeader('Entity Name','entities','name')}${this.sortHeader('Platform','entities','platform')}${this.sortHeader('Component / control','entities','target')}${this.sortHeader('Source','entities','source')}${this.sortHeader('Details','entities','details')}</tr></thead><tbody>${this.entityRows(migrate).map(({item:r,index:i})=>{const m=r.mapping,s=m.settings,enabled=migrate?r.source==='yaml':r.source==='ui';return `<tr data-entity-row="${i}" data-search="${escapeHTML([JSON.stringify(m),r.entity_name,r.entity_id,r.displaySource||r.source].filter(Boolean).join(' '))}"><td><input data-select="${i}" type="checkbox" aria-label="Select ${escapeHTML(s.name||s.control||s.component)}" ${enabled?'':'disabled'} ${this.selected.has(i)?'checked':''}></td><td>${this.entityNameCell(r,i)}</td><td>${m.platform}</td><td>${escapeHTML(s.component||'Named Control')} / ${escapeHTML(s.control||'media player')}</td><td>${r.displaySource||r.source}</td><td><details><summary>Settings</summary>${r.entity_id?`<p>${escapeHTML(r.entity_id)}</p>`:''}${r.cleanup_pending?'<p>Remove the transferred definition from Home Assistant YAML.</p>':''}${r.yaml_conflict?'<p>The definition configured via Home Assistant YAML changed after migration.</p>':''}<pre>${escapeHTML(JSON.stringify(s,null,2))}</pre></details></td></tr>`;}).join('')}</tbody></table></div>${migrate?`<label>Existing UI mappings <select id="collision"><option value="skip" ${this.collision!=='replace'?'selected':''}>Skip</option><option value="replace" ${this.collision==='replace'?'selected':''}>Replace</option></select></label>${this.button(`Review migration (${this.selected.size})`,'migrate')}`:`<label>Setting to edit <select id="edit-field">${this.editableFields().map(([v,label])=>`<option value="${v}" ${(this.editField||'name')===v?'selected':''}>${label}</option>`).join('')}</select></label>${this.editInput()}<p>The setting applies to every selected entity. All selected mappings must support it and pass validation.</p>${this.button('Review bulk edit','edit',this.selected.size?'class="filled"':'')}${this.button('Review deletion','delete',`class="danger ${this.selected.size?'filled':''}"`)}`}`;}
  renderTransport(){if(this.view==='export')return `<article class="card"><h2>Export portable YAML</h2><div class="tools">${this.button('Copy to clipboard','copy-export',this.exportDocument?'':'disabled')}${this.button('Download','export',this.exportDocument?'':'disabled')}</div><label><input id="effective" type="checkbox" ${this.effective?'checked':''}> Include active Home Assistant YAML mappings</label><p>Connection credentials and installation IDs are excluded.</p><pre id="export-document">${escapeHTML(this.exportDocument||'')}</pre></article>`;return `<article class="card"><h2>Import portable YAML</h2><label>Upload YAML <input id="file" type="file" accept=".yaml,.yml,.json"></label><label>Or paste YAML<textarea id="document" rows="14">${escapeHTML(this.document||'')}</textarea></label><label>Collisions <select id="collision"><option value="skip" ${this.collision!=='replace'?'selected':''}>Skip existing</option><option value="replace" ${this.collision==='replace'?'selected':''}>Replace existing</option></select></label><label><input id="transfer" type="checkbox" ${this.transfer?'checked':''}> Transfer ownership of colliding Home Assistant YAML mappings</label><p>Review discovery findings and changes before saving. Maximum 256 KiB and 1,000 mappings.</p>${this.button('Review import','import')}</article>`;}
  renderMonitor(){return `<div class="tools">${this.button(this.capture?'Stop capture':'Start capture','capture')}${this.button(this.paused?'Resume display':'Pause display','pause')}${this.button('Clear buffer','clear')}${this.button('Download capture','download-monitor')}</div><p><span id="monitor-status">${this.capture?'Capturing':'Capture stopped'} · ${this.frames.length}/500 frames retained.</span> Login credentials are redacted. Frames over 32 KiB are truncated. Capture covers this integration’s Core connection; refreshing the display adds no QRC requests.</p><p id="monitor-error" class="error" role="alert" hidden></p><div class="tools"><select id="direction" aria-label="Direction"><option value="">Both directions</option><option value="sent" ${this.direction==='sent'?'selected':''}>Sent</option><option value="received" ${this.direction==='received'?'selected':''}>Received</option></select><input id="monitor-search" placeholder="Filter method, ID, or payload" aria-label="Filter protocol frames" value="${escapeHTML(this.monitorSearch||'')}"></div><div class="table"><table><thead><tr><th>Time</th><th>Direction</th><th>ID</th><th>JSON-RPC frame</th></tr></thead><tbody id="monitor-rows">${this.frames.slice().reverse().map(frame=>this.monitorRow(frame)).join('')}</tbody></table></div>`;}
  renderReview(){return `<dialog id="review-dialog" aria-labelledby="review-title"><section class="review"><h2 id="review-title" tabindex="-1">Review changes</h2>${this.error?`<p class="error" role="alert">${escapeHTML(this.error)}</p>`:''}<div class="review-content"><table><thead><tr><th>Mapping</th><th>Action</th><th>Findings</th></tr></thead><tbody>${this.review.changes.map(c=>`<tr><td>${escapeHTML(c.identity.join(' / '))}</td><td>${escapeHTML(c.action)}${c.ownership_transfer?' · YAML ownership transfer':''}</td><td>${escapeHTML([c.warning,...(this.review.findings.find(f=>JSON.stringify(f.identity)===JSON.stringify(c.identity))?.issues||[])].filter(Boolean).join(', ')||'OK')}</td></tr>`).join('')}</tbody></table></div><p>Saving applies this batch together and reloads the Core entry once. Discovery and review never send control Set commands.</p><div class="review-actions">${this.button('Cancel','cancel')}${this.button(({create:'Create',edit:'Save',delete:'Delete'})[this.pending.operation]||'Confirm and save','save',`class="filled ${this.pending.operation==='delete'?'danger':''}"`)}</div></section></dialog>`;}
  captureForm(){
    this.shadowRoot.querySelectorAll('[data-name]').forEach(el=>{if(this.controls[el.dataset.name])this.controls[el.dataset.name].entityName=el.value;});
    const text=this.shadowRoot.querySelector('#document');if(text)this.document=text.value;
    const value=this.shadowRoot.querySelector('#edit-value');if(value)this.editValue=value.type==='checkbox'?value.checked:value.value;
  }
  render(){
    const hadReview=!!this.shadowRoot.querySelector('#review-dialog');
    const expanded=new Set([...this.shadowRoot.querySelectorAll("details[data-frame][open]")].map(el=>el.dataset.frame));
    if(this.view==='entities'&&!this.editableFields().some(([field])=>field===(this.editField||'name'))){this.editField='name';this.editValue='';}
    const titles={overview:'Dashboard',browser:'Components / Controls',entities:'Entities',monitor:'QRC Protocol Monitor',diagnostics:'Diagnostics',import:'Import YAML',export:'Export YAML',migrate:'Migrate from Home Assistant YAML'};
    this.shadowRoot.innerHTML=`<style>
      :host{display:block;height:100%;overflow:auto;background:var(--primary-background-color);color:var(--primary-text-color);font-family:var(--paper-font-body1_-_font-family,Roboto,Arial,sans-serif)}*{box-sizing:border-box}[hidden]{display:none!important}header{display:flex;align-items:center;gap:16px;padding:18px 24px;background:var(--card-background-color);border-bottom:1px solid var(--divider-color)}header h1{margin:0;font-size:23px}main{max-width:1400px;margin:auto;padding:24px}nav,.tools{display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin-bottom:20px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:18px;margin-bottom:32px}.card,.review{background:var(--card-background-color);border:1px solid var(--divider-color);border-radius:12px;padding:22px;text-align:left}.browser-config-card{margin-bottom:18px}.browser-config-card .tools:last-child{margin-bottom:0}.section-heading{display:flex;align-items:center;gap:8px;margin-bottom:12px}.section-heading h2{margin:0}.help{position:relative;display:inline-flex}.help-icon{display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;padding:0;margin:0;border-radius:50%;font-size:14px;font-weight:600;color:var(--secondary-text-color)}.help-icon:focus-visible{outline:2px solid var(--primary-color);outline-offset:3px}.card .help-tooltip{position:absolute;top:28px;left:-36px;z-index:2;width:300px;max-width:calc(100vw - 90px);padding:12px;border:1px solid var(--divider-color);border-radius:8px;background:var(--card-background-color);color:var(--primary-text-color);font-size:14px;line-height:1.5;box-shadow:0 3px 12px #0003;visibility:hidden;pointer-events:none}.help:hover .help-tooltip,.help:focus-within .help-tooltip{visibility:visible}.card h2{margin:0 0 12px;font-size:19px}.card .section-heading h2{margin:0}.card p,p{line-height:1.5;color:var(--secondary-text-color)}.card span{color:var(--primary-color)}button{cursor:pointer;color:var(--primary-color);background:var(--card-background-color);border:1px solid var(--divider-color);border-radius:8px;padding:10px 16px;font:inherit;margin-right:8px}button.sort-header{display:inline-flex;align-items:center;gap:6px;border:0;padding:0;margin:0;background:transparent;color:inherit;font-weight:600;text-align:left}.sort-icon{--mdc-icon-size:20px;width:20px;height:20px;flex:0 0 20px}.sort-icon.inactive{visibility:hidden}button.sort-header:hover{color:var(--primary-color)}.entity-label{display:inline-flex;align-items:center;gap:10px}.entity-label ha-state-icon{--mdc-icon-size:24px;width:24px;height:24px;flex:0 0 24px;color:var(--secondary-text-color)}button.entity-name{border:0;padding:0;margin:0;text-align:left;background:transparent}button.entity-name:hover{text-decoration:underline}button:hover{border-color:var(--primary-color)}button.filled{background:var(--primary-color);border-color:var(--primary-color);color:var(--text-primary-color,#fff)}button.danger{color:var(--error-color);border-color:var(--error-color)}button.danger.filled{background:var(--error-color);color:var(--text-primary-color,#fff)}button.filled:hover{filter:brightness(.92)}button:disabled{opacity:.5;cursor:not-allowed}.action-bar{position:sticky;bottom:0;z-index:3;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;padding:14px 18px;background:var(--card-background-color);border:1px solid var(--divider-color);border-radius:12px;box-shadow:0 -3px 12px #0001}.action-bar button{margin:0}.empty-state{padding:20px;border:1px dashed var(--divider-color);border-radius:8px}input,select,textarea{font:inherit;color:var(--primary-text-color);background:var(--card-background-color);border:1px solid var(--divider-color);border-radius:6px;padding:10px;max-width:100%}input[type=checkbox]{width:18px;height:18px;accent-color:var(--primary-color)}label{display:block;margin:12px 0}.edit-value-label>input,.edit-value-label>select,.edit-value-label>textarea{display:block;margin-top:8px}textarea{display:block;width:100%;margin:10px 0;font-family:monospace}.component-picker{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:12px 20px}.component-picker.single-column{grid-template-columns:1fr}.component-picker label{display:flex;align-items:flex-start;gap:10px;min-width:0;margin:4px 0;cursor:pointer}.component-picker input[type=checkbox]{flex:0 0 18px;margin:2px 0 0}.component-picker .component-label{display:flex;flex-direction:column;align-items:flex-start;gap:4px;min-width:0}.component-picker .component-name{color:var(--primary-text-color);font-size:inherit;overflow-wrap:anywhere;min-width:0}.component-picker .component-type{color:var(--secondary-text-color);font-size:12px;overflow-wrap:anywhere}.mapped-row{background:var(--secondary-background-color)}.mapped-row td{color:var(--disabled-text-color,var(--secondary-text-color))}.mapped-row input{opacity:.55}.mapped-badge{display:block;font-size:12px;margin-top:4px}button.mapped-link{padding:0;margin:4px 0 0;border:0;background:transparent;text-align:left}button.mapped-link:hover{text-decoration:underline}.component-group th{background:var(--secondary-background-color);color:var(--primary-text-color)}.table-filter{margin-bottom:8px}.table-filter+.table{margin-top:0}.table{overflow:auto;margin:20px 0}table{border-collapse:collapse;width:100%;text-align:left}th,td{padding:12px;border-bottom:1px solid var(--divider-color);vertical-align:top}th{color:var(--secondary-text-color)}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;max-width:800px}summary{cursor:pointer}.badge{font-size:12px}.error{padding:16px;border-radius:8px;background:var(--error-color);color:white}.message{padding:12px;border:1px solid var(--primary-color)}#review-dialog{width:min(900px,calc(100vw - 32px));max-height:calc(100dvh - 32px);padding:0;border:1px solid var(--divider-color);border-radius:12px;background:var(--card-background-color);color:var(--primary-text-color)}#review-dialog::backdrop{background:rgba(0,0,0,.5)}.review{margin:0;border:0}.review h2{margin-top:0}.review-content{overflow:auto;max-height:55dvh}.review-actions{display:flex;justify-content:flex-end;gap:12px;flex-wrap:wrap;margin-top:20px}.review-actions button{margin:0}@media(max-width:600px){main{padding:14px}header{padding:14px;flex-wrap:wrap}header select{width:100%}.grid{grid-template-columns:1fr}}
    </style><header><ha-icon-button id="back" data-action="back" label="Back to Connectivity"></ha-icon-button><h1>Q-SYS · ${titles[this.view]}</h1><select id="core" aria-label="Q-SYS Core">${this.cores.map(c=>`<option value="${escapeHTML(c.entry_id)}" ${c.entry_id===this.entry?'selected':''}>${escapeHTML(c.name)}</option>`).join('')}</select>${this.cores.length?this.button('Core settings','core-settings'):''}</header><main><nav>${Object.entries(titles).filter(([v])=>['overview','browser','entities','monitor'].includes(v)).map(([v,t])=>this.button(t,'navigate',`data-view="${v}" ${this.view===v?'aria-current="page"':''}`)).join('')}</nav>${this.error?`<p class="error" role="alert">${escapeHTML(this.error)}</p>`:''}${this.message?`<p class="message" role="status">${escapeHTML(this.message)}</p>`:''}${!this.cores.length?`<section class="card"><h2>Connect your first Core</h2><p>Open Settings → Devices &amp; services, choose Add integration, and search for Q-Sys QRC. Then return here to create entities. No YAML is required.</p>${this.button('Open integration settings','core-settings')}</section>`:this.view==='overview'?this.renderOverview():this.view==='browser'?this.renderBrowser():this.view==='entities'||this.view==='migrate'?this.renderEntities(this.view==='migrate'):this.view==='monitor'?this.renderMonitor():this.view==='diagnostics'?`<div class="grid">${this.cores.map(c=>`<article class="card"><h2>${escapeHTML(c.name)}</h2><p>${escapeHTML(c.status)}</p>${c.last_error?`<p role="alert">${escapeHTML(c.last_error)}</p>`:''}<p>Design information recorded when the Core was configured:</p><pre>${escapeHTML(JSON.stringify(c.engine,null,2))}</pre><p>Use the Protocol Monitor to inspect errors and polling responses. Core connection changes are available under Settings → Devices & services → Q-SYS → Reconfigure.</p></article>`).join('')}</div>`:this.renderTransport()}${this.review?this.renderReview():''}</main>`;
    this.updateEntityIcons();
    const editInput=this.shadowRoot.querySelector('#edit-value');if(editInput&&(this.resetEditBaseline||this.cleanEditValue===undefined)){this.cleanEditValue=editInput.type==='checkbox'?editInput.checked:editInput.value;this.resetEditBaseline=false;}
    const reviewDialog=this.shadowRoot.querySelector('#review-dialog');
    if(reviewDialog){reviewDialog.addEventListener('cancel',event=>{event.preventDefault();this.run(()=>this.action('cancel',{}));});reviewDialog.showModal();this.shadowRoot.querySelector('#review-title').focus();}
    else if(hadReview&&this.reviewReturnAction){this.shadowRoot.querySelector(`[data-action="${this.reviewReturnAction}"]`)?.focus();}
    const back=this.shadowRoot.querySelector('#back');if(back)back.path='M20,11H7.83L13.42,5.41L12,4L4,12L12,20L13.42,18.59L7.83,13H20V11Z';
    this.shadowRoot.querySelectorAll("details[data-frame]").forEach(el=>el.open=expanded.has(el.dataset.frame));
    if(this.view==='monitor')this.updateMonitor();
    this.filterComponentChoices();
    this.filterRows();
    const all=this.shadowRoot.querySelector("#all");if(all){const boxes=[...this.shadowRoot.querySelectorAll("tbody tr:not([hidden]) [data-select]:not(:disabled)")];all.checked=boxes.length>0&&boxes.every(box=>box.checked);all.indeterminate=boxes.some(box=>box.checked)&&!all.checked;}
  }
}
customElements.define('qsys-qrc-panel',QsysPanel);
