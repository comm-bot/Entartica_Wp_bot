from app.config import Settings
from app.services.availability import UnavailableAvailabilityProvider
from app.services.raipur_availability_provider import FailedAvailabilityProvider, build_raipur_availability_provider

class Query:
 def select(self,*_):return self
 def limit(self,*_):return self
 def execute(self):return type("R",(),{"data":[]})()
class Client:
 def table(self,_):return Query()
def test_unavailable_is_default_and_supabase_initialization_is_safe():
 assert isinstance(build_raipur_availability_provider(Settings(raipur_availability_provider="unavailable")),UnavailableAvailabilityProvider)
 assert build_raipur_availability_provider(Settings(raipur_availability_provider="supabase"),client=Client()).__class__.__name__=="SupabaseAvailabilityProvider"
 class Broken:
  def table(self,_):raise RuntimeError()
 assert isinstance(build_raipur_availability_provider(Settings(raipur_availability_provider="supabase"),client=Broken()),FailedAvailabilityProvider)
