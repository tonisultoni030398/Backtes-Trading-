let candles=[], visibleCount=0, manualJournal=[], manualPosition=null, autoTrades=[], chart, candleSeries, equityChart, equitySeries;
const $=id=>document.getElementById(id);
function status(msg,type=""){ $("status").textContent=msg; $("status").className="status "+type; }
function cfg(){return {symbol:$("symbol").value,interval:$("interval").value,start_date:$("start").value,end_date:$("end").value,strategy:$("strategy").value,initial_balance:Number($("balance").value),fast_ema:Number($("fast").value),slow_ema:Number($("slow").value),rsi_period:Number($("rsi").value),spread:Number($("spread").value),commission_per_trade:Number($("commission").value)}}
function intervalLabel(v){return {"1min":"M1","5min":"M5","15min":"M15","30min":"M30","1h":"H1","2h":"H2","4h":"H4","1day":"D1"}[v]||v}
async function checkHealth(){try{let r=await fetch("/api/health"),d=await r.json();$("apiStatus").textContent=d.api_key_configured?"BACKEND READY":"KEY BELUM DIATUR";$("apiStatus").style.color=d.api_key_configured?"#56d6a1":"#e7bd68"}catch{$("apiStatus").textContent="SERVER OFFLINE"}}
function setupChart(){
 if(!window.LightweightCharts){$("chart").textContent="Grafik gagal dimuat. Periksa koneksi internet.";return}
 chart=LightweightCharts.createChart($("chart"),{layout:{background:{color:"#0f151d"},textColor:"#91a0b2"},grid:{vertLines:{color:"#202a36"},horzLines:{color:"#202a36"}},rightPriceScale:{borderColor:"#273342"},timeScale:{borderColor:"#273342",timeVisible:true,secondsVisible:false},crosshair:{mode:1}});
 candleSeries=chart.addCandlestickSeries({upColor:"#56d6a1",downColor:"#ff7d83",borderUpColor:"#56d6a1",borderDownColor:"#ff7d83",wickUpColor:"#56d6a1",wickDownColor:"#ff7d83"});
 equityChart=LightweightCharts.createChart($("equityChart"),{layout:{background:{color:"#0f151d"},textColor:"#91a0b2"},grid:{vertLines:{color:"#202a36"},horzLines:{color:"#202a36"}},rightPriceScale:{borderColor:"#273342"},timeScale:{visible:false,borderColor:"#273342"}});
 equitySeries=equityChart.addLineSeries({color:"#e7bd68",lineWidth:2});
 const resize=()=>{chart.applyOptions({width:$("chart").clientWidth});equityChart.applyOptions({width:$("equityChart").clientWidth})};window.addEventListener("resize",resize);resize();
}
function chartTime(dt){return Math.floor(new Date(dt.replace(" ","T")+"Z").getTime()/1000)}
function renderCandles(){
 if(!candles.length||!candleSeries)return;
 const subset=candles.slice(0,Math.max(1,visibleCount));
 candleSeries.setData(subset.map(c=>({time:chartTime(c.time),open:c.open,high:c.high,low:c.low,close:c.close})));
 $("candleCount").textContent=`${subset.length} / ${candles.length} candle · ${$("symbol").value} ${intervalLabel($("interval").value)}`;
 $("replayLabel").textContent=subset.length?`Candle ${subset.length} dari ${candles.length} · ${subset[subset.length-1].time}`:"";
 $("prevBtn").disabled=visibleCount<=1;$("nextBtn").disabled=visibleCount>=candles.length;
 ["buyBtn","sellBtn","closeBtn","exportManual"].forEach(id=>$(id).disabled=!candles.length);
 chart.timeScale().fitContent();
}
async function loadData(){
 const c=cfg();if(!c.start_date||!c.end_date||c.start_date>c.end_date){status("Tanggal tidak valid.", "error");return}
 status("Mengambil dan memvalidasi candle dari Twelve Data…");
 try{const q=new URLSearchParams({symbol:c.symbol,interval:c.interval,start_date:c.start_date,end_date:c.end_date});const r=await fetch("/api/data?"+q);const d=await r.json();if(!r.ok)throw new Error(d.detail||"Gagal mengambil data");candles=d.candles;visibleCount=1;manualJournal=[];manualPosition=null;renderCandles();status(`Data valid: ${d.count} candle. Baris tidak valid dilewati: ${d.invalid_rows_skipped}.`, "ok")}
 catch(e){status(e.message,"error")}
}
async function runBacktest(){
 const c=cfg();if(!c.start_date||!c.end_date||c.start_date>c.end_date){status("Rentang tanggal tidak valid.","error");return}
 if(c.strategy==="ema_crossover"&&c.fast_ema>=c.slow_ema){status("EMA cepat harus lebih kecil dari EMA lambat.","error");return}
 $("runBtn").disabled=true;status("Mesin backtest sedang berjalan…");
 try{const r=await fetch("/api/backtest",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(c)});const d=await r.json();if(!r.ok)throw new Error(d.detail||"Backtest gagal");autoTrades=d.result.trades_detail;renderResults(d.result);candles=[];status(`Selesai. ${d.data_summary.count} candle dianalisis dari Twelve Data.`,"ok");$("exportBtn").disabled=false}
 catch(e){status(e.message,"error")}finally{$("runBtn").disabled=false}
}
function money(v){return (Number(v)<0?"−":"")+"$"+Math.abs(Number(v)).toFixed(2)}
function renderResults(r){
 $("netProfit").textContent=money(r.net_profit);$("netProfit").className=r.net_profit>=0?"positive":"negative";
 $("returnPct").textContent=r.return_pct.toFixed(2)+"%";$("returnPct").className=r.return_pct>=0?"positive":"negative";
 $("winRate").textContent=r.win_rate.toFixed(2)+"%";$("drawdown").textContent=r.max_drawdown_pct.toFixed(2)+"%";
 $("profitFactor").textContent=r.profit_factor===null?"—":r.profit_factor==="infinity"?"∞":r.profit_factor;
 $("tradeCount").textContent=r.trades;
 $("tradesBody").innerHTML=r.trades_detail.length?r.trades_detail.slice().reverse().map(t=>`<tr><td>${t.side.toUpperCase()}</td><td>${t.entry_time}</td><td>${Number(t.entry).toFixed(5)}</td><td>${t.exit_time}</td><td>${Number(t.exit).toFixed(5)}</td><td class="${t.pnl>=0?'positive':'negative'}">${money(t.pnl)}</td><td>${t.result}</td></tr>`).join(""):'<tr><td colspan="7" class="muted">Tidak ada transaksi berdasarkan aturan strategi pada periode ini.</td></tr>';
 $("caveat").textContent=r.caveat;
 if(equitySeries){equitySeries.setData(r.equity.map(e=>({time:chartTime(e.time),value:e.equity})));equityChart.timeScale().fitContent()}
}
function manualAction(action){
 if(!candles.length||visibleCount<1)return;
 const c=candles[visibleCount-1];
 if(action==="close"){if(!manualPosition){status("Tidak ada posisi manual yang terbuka.");return}const pnl=(c.close-manualPosition.entry)*(manualPosition.side==="BUY"?1:-1);manualJournal.push({...manualPosition,exit_time:c.time,exit:c.close,pnl,result:pnl>0?"win":pnl<0?"loss":"breakeven"});manualPosition=null;status(`Posisi ditutup. P/L harga per unit: ${pnl.toFixed(5)}.`,"ok")}
 else {if(manualPosition){status("Tutup posisi yang terbuka sebelum membuka posisi baru.","error");return}manualPosition={side:action.toUpperCase(),entry_time:c.time,entry:c.close};status(`${action.toUpperCase()} tercatat pada ${c.close}. Simulasi satu unit; belum memperhitungkan spread/komisi di jurnal manual.`,"ok")}
}
function downloadCSV(rows,name){if(!rows.length){status("Belum ada transaksi untuk diekspor.");return}const keys=Object.keys(rows[0]);const esc=v=>'"'+String(v??"").replaceAll('"','""')+'"';const csv=[keys.map(esc).join(","),...rows.map(r=>keys.map(k=>esc(r[k])).join(","))].join("\r\n");const url=URL.createObjectURL(new Blob(["\ufeff"+csv],{type:"text/csv;charset=utf-8"}));const a=document.createElement("a");a.href=url;a.download=name;a.click();URL.revokeObjectURL(url)}
$("loadBtn").addEventListener("click",loadData);$("runBtn").addEventListener("click",runBacktest);
$("prevBtn").addEventListener("click",()=>{visibleCount=Math.max(1,visibleCount-1);renderCandles()});$("nextBtn").addEventListener("click",()=>{visibleCount=Math.min(candles.length,visibleCount+1);renderCandles()});
["buyBtn","sellBtn","closeBtn"].forEach((id)=>$(id).addEventListener("click",()=>manualAction(id==="buyBtn"?"buy":id==="sellBtn"?"sell":"close")));
$("exportBtn").addEventListener("click",()=>downloadCSV(autoTrades,"goldlab-trades.csv"));
$("exportManual").addEventListener("click",()=>downloadCSV(manualJournal,"goldlab-manual-journal.csv"));
setupChart();checkHealth();
