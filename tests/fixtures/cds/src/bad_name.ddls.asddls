@AccessControl.authorizationCheck: #NOT_REQUIRED
define view entity bad_name as select from zt_one as o { key o.k as K }
