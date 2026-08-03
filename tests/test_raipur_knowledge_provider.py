from types import SimpleNamespace
from app.rag.raipur_knowledge_provider import RaipurKnowledgeProvider, _rank_service_rows
from app.services.raipur_answers import RaipurAnswer
def settings():return SimpleNamespace(raipur_knowledge_min_confidence=.65)
def candidate(score=.8,**extra):
 value={'content':'approved grounded text','source_filename':'raipur.md','confidence':score,'metadata':{'location_code':'raipur','customer_facing':True,'is_active':True,'approval_status':'approved','retrieval_priority':'service_specific'}};value.update(extra);return value
def provider(rows,answer=None):
 return RaipurKnowledgeProvider(object(),settings(),embed_query_fn=lambda q,s:[1],retrieve_candidates_fn=lambda c,v,limit:rows,answer_generator=answer or (lambda r,low_confidence:RaipurAnswer(r['content'],False,r['score'],(r['source_filename'],))))
def test_high_confidence_and_strongest_candidate():
 result=provider([candidate(.7,content='Raipur, Chhattisgarh'),candidate(.9,content='General\nLocation Information\nRaipur, Chhattisgarh')]).answer('Where is the Raipur location?')
 assert result.text.startswith('Our location is in Raipur, Chhattisgarh.') and result.source_filename=='raipur.md' and result.confidence==.9 and not result.low_confidence
def test_fail_closed_for_invalid_candidates_and_errors():
 for rows in ([],[candidate(.6)],[candidate(.9,content=' ')],[candidate(.9,source_filename=None)],[candidate(.9,metadata={'location_code':'indore'})],[candidate('bad')]):
  result=provider(rows).answer('where');assert result.text is None and result.low_confidence
 assert provider([candidate()],answer=lambda *_:RaipurAnswer(None,True,None,())).answer('where').low_confidence
 assert RaipurKnowledgeProvider(object(),settings(),embed_query_fn=lambda *_:(_ for _ in ()).throw(RuntimeError('secret'))).answer('where').low_confidence


def test_provider_removes_raw_metadata_and_fails_closed_when_only_metadata_remains():
 raw='''General\nLocation Information\nDocument Version\n1.0\nApproval Date\n21 July 2026\nStatus\nApproved for Chatbot Ingestion\nLocation\nRaipur, Chhattisgarh\nSource File\nraipur_location_information.docx'''
 result=provider([candidate(content=raw)]).answer('Where is the Raipur location?')
 assert 'Raipur, Chhattisgarh' in result.text
 for forbidden in ('Document Version','Approval Date','Approved for Chatbot Ingestion','General','raipur_location_information.docx','\n'):
  assert forbidden not in result.text
 only_metadata='Document Version\n1.0\nApproval Date\n21 July 2026\nStatus\nApproved for Chatbot Ingestion'
 assert provider([candidate(content=only_metadata)]).answer('Where is the Raipur location?').low_confidence


def test_services_general_and_hinglish_paths_remove_metadata_without_inventing_facts():
 service='''SERVICES\nDocument Version: 1.0\nBoating is available at Raipur.\nSource: private.docx'''
 services=provider([candidate(content=service)]).answer('What activities are available at Raipur?')
 assert services.text == 'Boating is available at Raipur.'
 assert 'Document Version' not in services.text and 'private.docx' not in services.text
 hinglish=provider([candidate(content='Location\nRaipur, Chhattisgarh')]).answer('Raipur location kahan hai?')
 assert 'Raipur, Chhattisgarh' in hinglish.text and 'Location\n' not in hinglish.text
 hindi=provider([candidate(content='General\nLocation Information\nRaipur, Chhattisgarh')]).answer('\u0930\u093e\u092f\u092a\u0941\u0930 \u0915\u093e \u0938\u094d\u0925\u093e\u0928 \u0915\u0939\u093e\u0901 \u0939\u0948?')
 assert hindi.text and 'Document Version' not in hindi.text and 'General' not in hindi.text
 assert provider([candidate(content='Price: 999')]).answer('What is the price?').low_confidence


def test_service_retrieval_requires_exact_service_code_and_rejects_cross_service_chunks():
 rows=[
  candidate(.9,content='Pontoon Celebration details',metadata={'location_code':'raipur','service_code':'pontoon_celebration','customer_facing':True,'is_active':True,'approval_status':'approved','retrieval_priority':'service_specific'}),
  candidate(.7,content='Pontoon Boat details',metadata={'location_code':'raipur','service_code':'pontoon_boat_ride','customer_facing':True,'is_active':True,'approval_status':'approved','retrieval_priority':'service_specific'}),
 ]
 result=provider(rows).answer_service_details('Tell me about Pontoon Boat','Pontoon Boat')
 assert result.text == 'Pontoon Boat details'
 assert 'Celebration' not in result.text
 assert provider([rows[0]]).answer_service_details('Tell me about Pontoon Boat','Pontoon Boat').low_confidence


def test_daycation_retrieval_excludes_staycation_content():
 rows=[
  candidate(.9,content='Staycation Combo content',metadata={'location_code':'raipur','service_code':'staycation_combo','customer_facing':True,'is_active':True,'approval_status':'approved','retrieval_priority':'service_specific'}),
  candidate(.7,content='Daycation Package content',metadata={'location_code':'raipur','service_code':'daycation_package','customer_facing':True,'is_active':True,'approval_status':'approved','retrieval_priority':'service_specific'}),
 ]
 result=provider(rows).answer_service_details('Tell me about Daycation Package','Daycation Package')
 assert result.text == 'Daycation Package content'
 assert 'Staycation' not in result.text


def test_exact_service_uses_full_question_and_keyword_fallback_without_cross_service_content():
 queries=[]; limits=[]
 rows=[
  candidate(.99,content='Pontoon Boat content',metadata={'location_code':'raipur','service_code':'pontoon_boat_ride','customer_facing':True,'is_active':True,'approval_status':'approved','retrieval_priority':'service_specific'}),
  candidate(.20,content='Jet Ski Ride is generally not recommended during pregnancy. Current participation eligibility must be confirmed with staff.',source_filename='active/services/jet_ski_ride.md',metadata={'location_code':'raipur','service_code':'jet_ski_ride','customer_facing':True,'is_active':True,'approval_status':'approved','retrieval_priority':'service_specific','section_heading':'Is the Jet Ski Ride suitable during pregnancy or for guests with health conditions?'}),
 ]
 def embed(question,_settings):queries.append(question);return [1]
 def retrieve(_client,_vector,limit):limits.append(limit);return rows
 value=RaipurKnowledgeProvider(object(),settings(),embed_query_fn=embed,retrieve_candidates_fn=retrieve,answer_generator=lambda row,low_confidence:RaipurAnswer(row['content'],False,row['score'],(row['source_filename'],)))
 result=value.answer_service_details('Can pregnent women ride jet ski?','Jet Ski','jet_ski_ride')
 assert queries == ['Can pregnent women ride jet ski?'] and limits == [1000]
 assert result.text and 'pregnancy' in result.text.casefold()
 assert result.source_filename == 'active/services/jet_ski_ride.md'
 assert result.section_heading and 'pregnancy' in result.section_heading.casefold()
 assert 'Pontoon' not in result.text


def test_duration_ranking_excludes_operating_hours_even_when_it_has_a_higher_score():
 metadata={'location_code':'raipur','service_code':'jet_ski_ride','customer_facing':True,'is_active':True,'approval_status':'approved','retrieval_priority':'service_specific'}
 rows=[
  candidate(.99,content='Current hours must be confirmed with the Entartica team before visiting.',metadata=metadata | {'section_heading':'Operating Hours'}),
  candidate(.70,content='Sessions generally last around 5 to 10 minutes, depending on operating conditions.',metadata=metadata | {'section_heading':'Duration'}),
 ]
 ranked=_rank_service_rows(rows,'What is the duration of Jet Ski?',detail_mode='duration')
 assert [item['metadata']['section_heading'] for item in ranked] == ['Duration','Operating Hours']
 result=provider(rows).answer_service_details('What is the duration of Jet Ski?','Jet Ski','jet_ski_ride',detail_mode='duration')
 assert result.section_heading == 'Duration'
 assert result.retrieved_section_headings == ('Duration',)
 assert result.text and '5 to 10 minutes' in result.text and 'current hours' not in result.text.casefold()


def test_parent_active_retrieval_does_not_require_a_chunk_level_active_filter():
 metadata={'location_code':'raipur','service_code':'jet_ski_ride','customer_facing':True,'approval_status':'approved','retrieval_priority':'service_specific'}
 active_parent=provider([candidate(.8,content='Jet Ski Ride safety requirements are confirmed with staff.',metadata=metadata)]).answer_service_details('Jet Ski safety','Jet Ski','jet_ski_ride')
 inactive_chunk=provider([candidate(.8,content='Jet Ski Ride safety requirements are confirmed with staff.',metadata=metadata | {'is_active':False})]).answer_service_details('Jet Ski safety','Jet Ski','jet_ski_ride')
 assert active_parent.text and inactive_chunk.low_confidence


def test_venue_overview_uses_only_approved_raipur_general_rows_and_prefers_overview_heading():
 general_metadata={'location_code':'raipur','service_code':'raipur_general','knowledge_type':'general','customer_facing':True,'is_active':True,'approval_status':'approved','section_heading':'About Entartica Raipur'}
 service_metadata={'location_code':'raipur','service_code':'speed_boat_ride','knowledge_type':'service','customer_facing':True,'is_active':True,'approval_status':'approved','retrieval_priority':'service_specific','section_heading':'Overview'}
 rows=[
  candidate(.9,content='Speed Boat is a passenger ride.',metadata=service_metadata),
  candidate(.8,content='Entartica Sea World Raipur is a water activity and celebration destination on Jhanjh Lake. It offers water sports such as Jet Ski and Speed Boat, non-motorised activities such as Kayaking, and celebration experiences.',source_filename='raipur_general_information.md',metadata=general_metadata),
 ]
 result=provider(rows).answer_venue_overview('Tell me about Entartica Raipur.')
 assert result.text and 'destination' in result.text.casefold() and 'speed boat' in result.text.casefold()
 assert result.source_filename=='raipur_general_information.md'
 assert 'passenger ride' not in result.text
