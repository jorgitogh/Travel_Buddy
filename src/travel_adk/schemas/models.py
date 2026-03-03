from pydantic import BaseModel, Field
from typing import List, Literal, Optional

TransportMode = Literal["coche", "avion"]

class TripFormInput(BaseModel):
    origin: str
    destination: str
    start_date: str
    end_date: str
    transport_mode: TransportMode
    interests: List[str] = Field(default_factory=list)


class TripRequest(TripFormInput):
    origin_iata: Optional[str] = None
    destination_iata: Optional[str] = None


class HotelOption(BaseModel):
    id: str
    name: Optional[str] = None
    area: Optional[str] = None
    checkin_date: str
    checkout_date: str
    price_total: Optional[float] = None
    currency: str = "EUR"
    estimated: bool = False
    deep_link: Optional[str] = None
    notes: Optional[str] = None


class HotelOptions(BaseModel):
    hotels: List[HotelOption] = Field(default_factory=list)


class TransportOption(BaseModel):
    id: str
    mode: TransportMode
    provider: Optional[str] = None
    departure_date: Optional[str] = None
    arrival_date: Optional[str] = None
    total_price: Optional[float] = None
    currency: str = "EUR"
    notes: Optional[str] = None


class TransportOptions(BaseModel):
    transports: List[TransportOption] = Field(default_factory=list)

class ItineraryDay(BaseModel):
    date: str
    blocks: List[str]

class Itinerary(BaseModel):
    summary: str
    days: List[ItineraryDay]
