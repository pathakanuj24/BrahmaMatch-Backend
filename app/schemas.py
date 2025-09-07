# app/schemas.py
from proto import Enum
from pydantic import BaseModel, Field, constr, confloat, conint
from typing import Optional, List
import datetime

from enum import Enum
phone_var = constr(strip_whitespace=True, min_length=6)



class SendOTPIn(BaseModel):
    phone: phone_var = Field(..., example="+919876543210")

class VerifyOTPIn(BaseModel):
    phone: phone_var = Field(..., example="+919876543210")
    code: str = Field(..., example="123456")

class SalaryRange(str, Enum):
    BELOW_1L = "below_1l"
    _1_TO_2L = "1_2l"
    _2_TO_3L = "2_3l"
    _3_TO_5L = "3_5l"
    _5_TO_7L = "5_7l"
    _7_TO_10L = "7_10l"
    _10_TO_15L = "10_15l"
    _15_TO_25L = "15_25l"
    ABOVE_25L = "above_25l"

class UserOut(BaseModel):
    user_id: str
    phone: str
    is_verified: bool
    created_at: datetime.datetime
    last_login: Optional[datetime.datetime] = None

HeightT = confloat(ge=0)          # e.g. 175.5
AgeT = conint(ge=0, le=150)       # reasonable upper bound
GotraT = constr(strip_whitespace=True, min_length=1)

class ProfileIn(BaseModel):
    full_name: Optional[str] = None
    fathers_name: Optional[str] = None
    mothers_name: Optional[str] = None
    interests: Optional[List[str]] = None
    date_of_birth: Optional[datetime.date] = None
    birth_place: Optional[str] = None
    education: Optional[str] = None
    home_town: Optional[str] = None
    mama_pariwar: Optional[str] = None
    manglik: Optional[bool] = None
    height: Optional[HeightT] = Field(None, description="Height in centimeters (e.g. 175 or 172.5)")
    age: Optional[AgeT] = Field(None, description="Age in years (integer)")
    gotra: Optional[GotraT] = Field(None, description="Gotra / clan name")
    profile_image: Optional[str] = Field(None, description="Base64-encoded profile image")
    gallery_images: Optional[List[str]] = Field(default_factory=list, description="Base64-encoded gallery images")
    education: Optional[str] = Field(None, description="Educational qualification")
    job_employer: Optional[str] = Field(None, description="Employer / company name")
    job_designation: Optional[str] = Field(None, description="Job title / designation")
    job_location: Optional[str] = Field(None, description="Work location (city/state)")
    salary_range: Optional[SalaryRange] = Field(
        None,
        description="Salary range selected from dropdown (values represent lakhs per year)"
    )
    about_me: Optional[str] = Field(None, description="Free-text 'about me' section")


class ProfileOut(ProfileIn):
    user_id: str
    created_at: datetime.datetime
    updated_at: Optional[datetime.datetime] = None