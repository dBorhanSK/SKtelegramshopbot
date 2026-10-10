-- نمونه دسته و محصول
insert into categories (name_fa,name_en,sort_order) values
('محصولات دیجیتال','Digital Products',1),
('تبلیغات','Advertising',2);

insert into products
(category_id,name_fa,name_en,description_fa,description_en,price,stock,digital_content)
select id,'محصول نمونه','Sample Product','توضیح محصول نمونه','Sample product description',100000,100,'YOUR_DIGITAL_FILE_OR_CODE'
from categories where name_fa='محصولات دیجیتال' limit 1;
