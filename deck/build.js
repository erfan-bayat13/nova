const pptxgen = require("pptxgenjs");
const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.title = "Nova: the interface that forms around you";
const BG="0B0D12", CARD="161A22", TXT="F5F5F7", MUT="9AA0AB", ACC="8FD3FF", CLOUD="FFC78A";
const H="Cambria", B="Calibri";

function base(notes){ const s=pres.addSlide(); s.background={color:BG}; if(notes) s.addNotes(notes); return s; }
function title(s,t,sub){
  s.addText(t,{x:0.6,y:0.4,w:8.8,h:0.9,fontFace:H,fontSize:36,bold:true,color:TXT,margin:0,isTextBox:true,valign:"top"});
  if(sub) s.addText(sub,{x:0.6,y:1.3,w:8.8,h:0.5,fontFace:B,fontSize:16,color:MUT,margin:0,isTextBox:true,valign:"top"});
}
function orb(s,cx,cy,r){
  s.addShape(pres.shapes.OVAL,{x:cx-r*1.7,y:cy-r*1.7,w:r*3.4,h:r*3.4,fill:{color:ACC,transparency:94},line:{type:"none"}});
  s.addShape(pres.shapes.OVAL,{x:cx-r*1.3,y:cy-r*1.3,w:r*2.6,h:r*2.6,fill:{color:ACC,transparency:88},line:{type:"none"}});
  s.addShape(pres.shapes.OVAL,{x:cx-r,y:cy-r,w:r*2,h:r*2,fill:{color:"1B2230"},line:{color:ACC,width:1.5}});
  s.addShape(pres.shapes.OVAL,{x:cx-r*0.45,y:cy-r*0.55,w:r*0.9,h:r*0.9,fill:{color:ACC,transparency:35},line:{type:"none"}});
}
function card(s,x,y,w,h,head,body,opts={}){
  s.addShape(pres.shapes.ROUNDED_RECTANGLE,{x,y,w,h,rectRadius:0.12,fill:{color:CARD},line:{color:"232A36",width:0.75}});
  s.addText(head,{x:x+0.25,y:y+0.2,w:w-0.5,h:0.45,fontFace:B,fontSize:opts.hs||18,bold:true,color:opts.hc||TXT,margin:0,isTextBox:true,valign:"top"});
  s.addText(body,{x:x+0.25,y:y+0.7,w:w-0.5,h:h-0.9,fontFace:B,fontSize:14,color:MUT,margin:0,isTextBox:true,valign:"top"});
}

// 1 Title
let s=base("Open with the question. Let it sit. Then: we built the answer. A blank screen, one orb, and a voice.");
orb(s,7.6,2.8,0.9);
s.addText("Nova",{x:0.6,y:0.7,w:5,h:0.6,fontFace:B,fontSize:18,color:ACC,bold:true,margin:0,isTextBox:true});
s.addText("If AI understands what you want, why should you have to find the right app?",{x:0.6,y:1.4,w:5.6,h:2.2,fontFace:H,fontSize:34,bold:true,color:TXT,margin:0,isTextBox:true,valign:"top"});
s.addText("A blank canvas and a voice. The interface forms around you, then goes away.",{x:0.6,y:3.9,w:5.4,h:0.8,fontFace:B,fontSize:16,color:MUT,margin:0,isTextBox:true,valign:"top"});
s.addText("Working name. Hackathon, 7 Nov 2026",{x:0.6,y:5.0,w:6,h:0.3,fontFace:B,fontSize:11,color:MUT,margin:0,isTextBox:true});

// 2 Problem
s=base("We have spent forty years teaching people to navigate software. The AI era should flip that: software navigates to the person.");
title(s,"We adapt to software","Every task starts the same way: find the app, find the screen, find the button.");
const probs=[["Apps","One per job. Open, switch, close."],["Windows","Tabs and panes you arrange by hand."],["Chat boxes","Even AI makes you type and read."]];
probs.forEach((p,i)=>card(s,0.6+i*3.05,2.3,2.85,1.9,p[0],p[1],{hs:24}));
s.addText("The intelligence is already there. The interface is the bottleneck.",{x:0.6,y:4.6,w:8.8,h:0.5,fontFace:H,fontSize:20,italic:true,color:ACC,margin:0,isTextBox:true});

// 3 Vision
s=base("This is the whole product in three beats. Say it, it forms, it dissolves. No navigation anywhere.");
title(s,"The vision: an interface that exists only for this moment");
const beats=[["1","You say what you are doing","\"I'm cooking pasta for four.\""],["2","The interface forms","Recipe, ingredients and a timer appear. Say \"make it six\" and the same widgets update."],["3","You finish, it dissolves","Back to a single orb. Nothing left to close or clean up."]];
beats.forEach((b,i)=>{
  const x=0.6+i*3.05;
  s.addShape(pres.shapes.OVAL,{x:x,y:1.9,w:0.6,h:0.6,fill:{color:ACC},line:{type:"none"}});
  s.addText(b[0],{x:x,y:1.9,w:0.6,h:0.6,fontFace:B,fontSize:18,bold:true,color:BG,align:"center",valign:"middle",margin:0,isTextBox:true});
  s.addText(b[1],{x:x,y:2.7,w:2.8,h:0.7,fontFace:B,fontSize:18,bold:true,color:TXT,margin:0,isTextBox:true,valign:"top"});
  s.addText(b[2],{x:x,y:3.45,w:2.8,h:1.3,fontFace:B,fontSize:14,color:MUT,margin:0,isTextBox:true,valign:"top"});
});
s.addText("No apps. No chat window. No navigation. The speaking replaces the typing.",{x:0.6,y:4.85,w:8.8,h:0.4,fontFace:B,fontSize:14,italic:true,color:ACC,margin:0,isTextBox:true});

// 4 Beyond the screen
s=base("This is where Nova stops being a voice assistant. It has eyes, it asks before it looks, and it works while you are away. Morning briefing is the first background agent.");
title(s,"Nova sees, asks first, and keeps working","An ambient assistant that speaks up only when something matters.");
card(s,0.6,2.2,2.85,2.6,"Eyes","Camera, screen, or a rectangle you drag around part of the screen. One frame, on request.");
card(s,3.6,2.2,2.85,2.6,"Asks before looking","\"Want me to take a look at your screen?\" Only a spoken yes opens the camera.");
card(s,6.6,2.2,2.85,2.6,"Background agents","Watch a build, brief you at 8, follow up on a timer. Results are spoken or queued.",{});
s.addText("Built: eyes and ask-then-look. Designed: background agents.",{x:0.6,y:5.0,w:8.8,h:0.3,fontFace:B,fontSize:12,color:MUT,margin:0,isTextBox:true});

// 5 Demo
s=base("Three scenes. Cooking shows the interface forming. Vision shows eyes. Escalation shows the system growing. Scene three is the one to land.");
title(s,"Three moments in the demo");
const demo=[["Form","\"Pasta for four\" gives recipe and timer. \"Make it six\" updates the same widgets. \"I'm done\" dissolves them.",ACC],["See","Hold an ingredient to the camera: \"What can I make with this?\" Answered on the device.",ACC],["Grow","A hard request goes to Claude, a brand-new widget appears. Ask again and it is instant and local.",CLOUD]];
demo.forEach((d,i)=>{
  const y=1.6+i*1.2;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE,{x:0.6,y,w:8.8,h:1.05,rectRadius:0.12,fill:{color:CARD},line:{color:"232A36",width:0.75}});
  s.addText(d[0],{x:0.85,y,w:1.5,h:1.05,fontFace:H,fontSize:26,bold:true,color:d[2],valign:"middle",margin:0,isTextBox:true});
  s.addText(d[1],{x:2.4,y,w:6.8,h:1.05,fontFace:B,fontSize:15,color:TXT,valign:"middle",margin:0,isTextBox:true});
});

// 6 Architecture
s=base("Local first because it is private, instant and free. Cloud only when the problem needs it. One voice throughout, so the user never needs to know which brain answered.");
title(s,"Local first, frontier when needed");
const boxes=[["You","voice, camera, screen",0.6,TXT],["Orb + canvas","draws widgets, plays voice",2.7,TXT],["Orchestrator","routes every request",4.8,TXT],["Local model","LFM3-Omni-2B, on this Mac",7.0,ACC]];
boxes.forEach(b=>{
  s.addShape(pres.shapes.ROUNDED_RECTANGLE,{x:b[2],y:2.0,w:2.0,h:1.3,rectRadius:0.12,fill:{color:CARD},line:{color:b[3]===ACC?ACC:"232A36",width:1}});
  s.addText(b[0],{x:b[2],y:2.15,w:2.0,h:0.45,fontFace:B,fontSize:16,bold:true,color:b[3],align:"center",margin:0,isTextBox:true});
  s.addText(b[1],{x:b[2]+0.1,y:2.65,w:1.8,h:0.55,fontFace:B,fontSize:12,color:MUT,align:"center",margin:0,isTextBox:true,valign:"top"});
});
[2.6,4.7,6.8].forEach(x=>s.addText("›",{x:x,y:2.3,w:0.2,h:0.6,fontFace:B,fontSize:28,color:MUT,align:"center",margin:0,isTextBox:true}));
s.addShape(pres.shapes.ROUNDED_RECTANGLE,{x:4.8,y:4.0,w:4.2,h:1.0,rectRadius:0.12,fill:{color:CARD},line:{color:CLOUD,width:1}});
s.addText("Claude (cloud)",{x:4.8,y:4.08,w:4.2,h:0.4,fontFace:B,fontSize:16,bold:true,color:CLOUD,align:"center",margin:0,isTextBox:true});
s.addText("hard reasoning, builds new widgets and skills",{x:4.9,y:4.5,w:4.0,h:0.4,fontFace:B,fontSize:12,color:MUT,align:"center",margin:0,isTextBox:true});
s.addText("only when needed",{x:0.6,y:4.2,w:3.8,h:0.5,fontFace:B,fontSize:14,italic:true,color:CLOUD,align:"right",margin:0,isTextBox:true,valign:"middle"});
s.addText("↓",{x:6.7,y:3.35,w:0.6,h:0.6,fontFace:B,fontSize:24,color:CLOUD,align:"center",margin:0,isTextBox:true});

// 7 Cloud teaches
s=base("This is the pitch in one line. Every hard request makes the local model more capable. The system gains abilities as you use it.");
title(s,"The cloud teaches, the local model remembers");
const loop=[["Hard request","Local model can't do it",TXT],["Claude builds it","A new widget and skill",CLOUD],["Saved","Added to the local model's toolbox",ACC],["Next time","Instant, on-device, free",ACC]];
loop.forEach((l,i)=>{
  const x=0.6+i*2.25;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE,{x,y:2.0,w:2.0,h:1.7,rectRadius:0.12,fill:{color:CARD},line:{color:l[2]===TXT?"232A36":l[2],width:1}});
  s.addText(l[0],{x:x+0.15,y:2.2,w:1.7,h:0.7,fontFace:B,fontSize:17,bold:true,color:l[2],margin:0,isTextBox:true,valign:"top"});
  s.addText(l[1],{x:x+0.15,y:2.9,w:1.7,h:0.7,fontFace:B,fontSize:13,color:MUT,margin:0,isTextBox:true,valign:"top"});
  if(i<3) s.addText("›",{x:x+2.0,y:2.55,w:0.25,h:0.5,fontFace:B,fontSize:24,color:MUT,align:"center",margin:0,isTextBox:true});
});
s.addText("An interface that gets better the more you use it, without a software update.",{x:0.6,y:4.3,w:8.8,h:0.6,fontFace:H,fontSize:20,italic:true,color:ACC,margin:0,isTextBox:true});

// 8 Trust
s=base("An assistant that sees must earn trust. These rules are designed in, not bolted on. Pause the camera and every watcher in one gesture.");
title(s,"Seeing only works with trust","Rules built in from the start");
const rules=[["Ask first","Nothing is captured without a spoken yes."],["Never stored","Frames live in memory for one call, then are dropped."],["Visible","The orb changes state whenever it is looking."],["Local only","No image leaves the Mac. Claude gets text, not pixels."]];
rules.forEach((r,i)=>card(s,0.6+(i%2)*4.5,1.95+Math.floor(i/2)*1.6,4.3,1.4,r[0],r[1]));

// 9 Proof
s=base("These are measured on the real model on an 8 GB M2, not mock numbers. The point: a 2B model on a laptop is already fast enough to feel like a conversation.");
title(s,"It already works on an 8 GB laptop","Measured on the real model, on this Mac");
const stats=[["0.3s","reply starts after you let go"],["0.17s","to cut it off when you interrupt"],["3-5s","to look and answer, warm"],["1.6GB","server memory, flat"]];
stats.forEach((st,i)=>{
  const x=0.6+i*2.25;
  s.addText(st[0],{x,y:2.2,w:2.1,h:1.0,fontFace:H,fontSize:48,bold:true,color:ACC,margin:0,isTextBox:true,valign:"middle"});
  s.addText(st[1],{x,y:3.25,w:2.0,h:0.8,fontFace:B,fontSize:14,color:MUT,margin:0,isTextBox:true,valign:"top"});
});
s.addText("Voice-to-voice with its own voice, 100+ turn conversations with perfect recall.",{x:0.6,y:4.5,w:8.8,h:0.4,fontFace:B,fontSize:14,italic:true,color:TXT,margin:0,isTextBox:true});

// 10 Roadmap
s=base("Close on the vision. Honest status: voice and eyes are real. Canvas creation and Claude-built widgets are the next build. End on the first slide's question.");
title(s,"Where it goes next");
const cols=[["Built",ACC,["Voice orb, speech to speech","Camera, screen, area vision","Ask-then-look consent","Canvas with widgets (parked)"]],["Next",CLOUD,["Canvas creation by voice","Claude builds new widgets","Saved for local reuse"]],["Later",MUT,["Morning briefing agent","Watch-and-tell agents","Router to pick who helps"]]];
cols.forEach((c,i)=>{
  const x=0.6+i*3.05;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE,{x,y:1.6,w:2.85,h:2.9,rectRadius:0.12,fill:{color:CARD},line:{color:"232A36",width:0.75}});
  s.addText(c[0],{x:x+0.25,y:1.8,w:2.4,h:0.5,fontFace:H,fontSize:22,bold:true,color:c[1],margin:0,isTextBox:true});
  s.addText(c[2].map((t,j)=>({text:t,options:{bullet:true,breakLine:j<c[2].length-1}})),{x:x+0.25,y:2.45,w:2.4,h:1.9,fontFace:B,fontSize:14,color:TXT,margin:0,isTextBox:true,valign:"top",paraSpaceAfter:6});
});
s.addText("Stop finding the right app. Just say what you're doing.",{x:0.6,y:4.8,w:8.8,h:0.5,fontFace:H,fontSize:22,bold:true,color:TXT,margin:0,isTextBox:true});

pres.writeFile({fileName:"nova-deck.pptx"}).then(()=>console.log("ok"));
