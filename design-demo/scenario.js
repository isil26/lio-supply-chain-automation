const products = {
  books:{tab:'Art books',icon:'book',tone:'',title:'Secure delivery for 5,900 art books',why:'Karton is holding the full shortfall. Confirm a delivery slot and freight cost before releasing the partial order.',value:'€12,390',valueLabel:'5,900 × €2.10 per book',owner:'Buyer',due:'Sun ~06:00',timing:'Target Sun 22 Nov around 06:00 CET at the latest. The 24-hour offer expires Sunday morning. Its exact expiry is unconfirmed.',queue:'Secure art-book delivery',short:'5,900 books · Collector’s',offers:[
    {key:'kartonBooks',detail:'5,900 available at €2.10 each',summary:'Karton can hold 5,900 finished art books free of charge. The €2.10 unit price is valid for 24 hours from the morning offer. Loading takes up to four hours after a formal order. Warta Trans still needs to confirm the delivery window.'}
  ]},
  cards:{tab:'Game cards',icon:'plane',tone:'blue',title:'Secure the 28,000-card handover',why:'Hwaseong’s air lot is already in transit. Get a timed Frankfurt arrival and reserve customs clearance and the Hamburg dock before it lands.',value:'6,800 cards',valueLabel:'Still short after the air lot arrives',owner:'Logistics',due:'Tonight',timing:'Start Saturday evening, before the air lot lands. The carrier has yet to confirm a timed arrival.',queue:'Secure card handover',short:'28,000 cards · Both editions',offers:[
    {key:'hwaseong',detail:'28,000 in transit · handover unconfirmed',summary:'The 28,000-card lot departed Incheon for Frankfurt. The carrier has yet to confirm an arrival time. The remaining 20,000 are expected in Hamburg on 24 November.'},
    {key:'boise',detail:'36,000 at origin · after launch',summary:'Boise has 36,000 cards packed at its dock. Even premium freight cannot deliver the missing 6,800 in time. A written EXW confirmation or a nominated forwarder is required for release.'}
  ]},
  statues:{tab:'Statues',icon:'shield',tone:'',title:'Request a sort of the held statues',why:'Neither supplier can deliver by launch. Ask Quality to inspect the 5,600 units already in Hamburg and release the pieces that pass.',value:'3,400 statues',valueLabel:'Needed for Collector’s boxes',owner:'Quality & Compliance',due:'Before Sun shift',timing:'Planning target before the Sunday 06:00 pack-out shift. Inspection time and release quantity are unconfirmed.',queue:'Request statue inspection',short:'3,400 statues · Collector’s',offers:[
    {key:'pune',detail:'5,000 by sea · 28 Nov',summary:'Pune cannot supply 3,400 statues in Hamburg by cutoff. Its next 5,000 units are due by sea on 28 November.'},
    {key:'dongguan',detail:'10,000 by sea · 27 Nov',summary:'Dongguan cannot deliver the missing 3,400 by cutoff. Its next sea shipment of 10,000 pieces is due in Hamburg on 27 November.'}
  ]},
  sleeves:{tab:'Sleeves',icon:'truck',tone:'warm',title:'Verify the revision C sleeve delivery',why:'Karton’s truck should cover the 6,000-sleeve gap for Standard. Check the signed receipt and revision before counting the stock.',value:'20,000 sleeves',valueLabel:'Already ordered from Karton Nowak',owner:'Hamburg warehouse',due:'Tonight',timing:'Check the Hamburg receipt on Saturday evening, when Warta Trans is due at the warehouse.',queue:'Verify sleeve receipt',short:'20,000 sleeves · Standard',offers:[
    {key:'kartonSleeves',detail:'20,000 rev C · receipt pending',summary:'Warta Trans was due to deliver 20,000 revision C sleeves on Saturday evening. Karton has yet to receive signed proof of delivery. Additional digital production takes at least 36 hours.'},
    {key:'packright',detail:'No revision C stock for launch',summary:'PackRight has no released revision C sleeves for Sunday. Its revision B stock cannot be used for this launch.'}
  ]},
  cases:{tab:'Game cases',icon:'box',tone:'blue',title:'Arrange terminal pickup',why:'350,000 clear game cases have landed in Hamburg. Nordhav must confirm release and a truck slot for the 32,000 needed on the Standard line.',value:'32,000 cases',valueLabel:'Needed before inbound pickup',owner:'Logistics',due:'Tonight',timing:'Request release and weekend pickup on Saturday evening, ahead of Sunday pack-out.',queue:'Arrange case pickup',short:'32,000 cases · Standard',offers:[
    {key:'packrightCases',detail:'350,000 at Hamburg terminal · pickup pending',summary:'PackRight confirms the cases were discharged on 19 November. Under FOB terms Nordhav controls release and trucking. PackRight can provide the origin handover documents.'}
  ]}
};
const orderedTasks=['cards','sleeves','cases','books','statues'];
const editions=[{name:'Collector’s Edition',target:72000,median:62550,unitLoss:120,icon:'layers',cls:'collector'},{name:'Standard Edition',target:640000,median:614650,unitLoss:32,icon:'box',cls:'standard'}];

// Each reply addresses the actual option in its supplier thread.
const replyTerms = {
  kartonBooks: {
    approve:'Please maintain the free hold on 5,900 finished art books at €2.10 each. Before we release the partial order, please confirm the loading and Hamburg delivery slots and any freight premium.',
    decline:'We will pass on the express art-book option for launch. Please keep the existing purchase order on its current schedule.',
    negotiate:'Could Warta quote standard and dedicated trucks for the held 5,900 books? If a full load misses Sunday pack-out, what split can arrive earlier, at what additional cost, and until when can you hold it?'
  },
  hwaseong: {
    approve:'Please proceed with handover coordination for the 28,000 cards already on AWB 020-48113256. Please share the flight ETA, customs paperwork and earliest Hamburg dock time.',
    decline:'We will pass on using the later 20,000 cards for launch recovery. Please keep the original orders and the 28,000-card air shipment on schedule.',
    negotiate:'Can your forwarder pre-clear the 28,000 cards and arrange a priority truck from Frankfurt? Please compare earliest Hamburg handover, quantity and incremental cost with the standard transfer.'
  },
  boise: {
    approve:'We accept post-launch pickup planning for the 36,000 cards at Boise. Please send the pickup address, packing details and latest forwarder nomination time so our buyer can arrange release.',
    decline:'We will pass on expedited transport from Boise for launch because it misses Sunday pack-out. Please retain the existing lot pending our forwarder instructions.',
    negotiate:'For recovery after launch, could you split the 36,000 cards into an initial uplift and a lower-cost balance? Please quote the earliest collection, landed timing and freight cost for each.'
  },
  pune: {
    approve:'Please continue checking weekend inspector availability for the 5,600 statues already in Hamburg. Please share the earliest slot, throughput and fee for our Quality team to review.',
    decline:'We will pass on the 28 November sea arrival as a launch recovery option. Please maintain the existing shipment schedule.',
    negotiate:'Could you provide a second inspector or fund a local sorting team? We need 3,400 released units. Please quote staged inspection times and cost, subject to our Quality team’s release.'
  },
  dongguan: {
    approve:'We acknowledge the 10,000-unit sea shipment as post-launch replenishment. Please share the arrival notice and first release slot for NHSU6120458.',
    decline:'We will pass on this shipment for Sunday recovery because its arrival is 27 November. Please keep the original sea booking.',
    negotiate:'Given the 27 November sea arrival, could you arrange partial container release at Hamburg? Please compare first available quantities, release times and onward freight charges.'
  },
  kartonSleeves: {
    approve:'Please continue the existing 20,000-unit revision C sleeve delivery. Please send signed proof of receipt, lot revision and accepted quantity for PO 7K21M.',
    decline:'We decline the additional digital print run for launch. Please keep the 20,000 revision C sleeves on PO 7K21M on schedule and send proof of receipt.',
    negotiate:'If the 20,000 sleeves cannot all be unloaded tonight, can Warta prioritize 6,000 revision C units? Please give the first unload time, remaining quantity and any extra handling charge.'
  },
  packright: {
    approve:'Please proceed with preparing a revision C production proposal for after launch. We will provide approved artwork separately. Please confirm lead time and price before starting production.',
    decline:'We decline revision B sleeves for this launch. Only revision C is released for packing. Please keep revision B stock segregated.',
    negotiate:'Once you have the revision C artwork, could you quote a small digital first batch followed by offset production? Please include setup cost, minimum quantities and earliest release.'
  },
  packrightCases: {
    approve:'Please provide the origin handover documents for NHSU4471921 and PO 4500318738 line 20. We will coordinate terminal release and the Hamburg truck directly with Nordhav.',
    decline:'We will pass on additional supplier-side transport arrangements for the cases. Our Hamburg team will work with Nordhav on the existing shipment.',
    negotiate:'Could you provide carton and pallet breakdowns so Nordhav can assess a first release of 32,000 cases? Please identify any documents needed for a split pickup and when you can provide them.'
  }
};
