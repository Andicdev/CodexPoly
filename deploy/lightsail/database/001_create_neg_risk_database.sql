CREATE DATABASE codexpoly_neg_risk
    WITH
    OWNER = codexpoly_admin
    ENCODING = 'UTF8'
    TEMPLATE = template0;

REVOKE ALL ON DATABASE codexpoly_neg_risk FROM PUBLIC;
GRANT CONNECT ON DATABASE codexpoly_neg_risk TO codexpoly_app;
